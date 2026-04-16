#!/usr/bin/env python3
"""
scripts/heartbeat_insights.py — Poll social posts for insights updates.

Run from the main heartbeat (or as a standalone cron job) to fetch
Facebook/TikTok insights for posts that are:
  - Posted (posted_at not null)
  - Older than 1 hour
  - Not polled in the last 30 minutes

Debounce: max 1 Facebook fetch + 1 TikTok fetch per heartbeat run.

Usage:
  python scripts/heartbeat_insights.py [--dry-run]
"""

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

import db
from modules.pipeline.models import SocialPlatformConfig
from modules.social.facebook import FacebookPublisher
from modules.social.tiktok import TikTokPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("heartbeat_insights")


def load_platform_config(platform: str) -> SocialPlatformConfig:
    """Load SocialPlatformConfig for a platform from DB credentials."""
    from modules.pipeline.models import SocialPlatformConfig

    if platform == "facebook":
        page_id = db.get_credential("facebook", "page_id")
        access_token = db.get_credential("facebook", "access_token")
        return SocialPlatformConfig(
            platform="facebook",
            page_id=page_id,
            access_token=access_token,
        )
    else:  # tiktok
        advertiser_id = db.get_credential("tiktok", "advertiser_id")
        access_token = db.get_credential("tiktok", "access_token")
        return SocialPlatformConfig(
            platform="tiktok",
            advertiser_id=advertiser_id,
            access_token=access_token,
        )


def fetch_facebook_insights(post_id: str) -> dict | None:
    """Fetch insights for a Facebook post. Returns None on failure."""
    config = load_platform_config("facebook")
    publisher = FacebookPublisher(config)
    return publisher.get_post_insights(post_id)


def fetch_tiktok_insights(post_id: str) -> dict | None:
    """Fetch insights for a TikTok post. Returns None on failure."""
    config = load_platform_config("tiktok")
    publisher = TikTokPublisher(config)
    return publisher.get_post_insights(post_id)


def run(dry_run: bool = False) -> dict:
    """Main entry point. Returns a summary dict."""
    db.init_db()
    stats = {"facebook": {"fetched": 0, "skipped": 0, "errors": 0},
             "tiktok":   {"fetched": 0, "skipped": 0, "errors": 0},
             "total": 0}

    # Posts needing insights: >1h old, not polled in last 30min
    try:
        pending = db.get_posts_needing_insights(hours_old=1, min_polling_interval_minutes=30)
    except Exception as e:
        logger.error(f"Failed to query pending posts: {e}")
        return stats

    if not pending:
        logger.info("No posts need insights polling right now.")
        return stats

    logger.info(f"Found {len(pending)} posts needing insights polling.")

    # Debounce: max 1 per platform per run
    fb_done = False
    tt_done = False

    for post in pending:
        platform = post.get("platform", "")
        post_id = post.get("post_id")
        posted_at = post.get("posted_at")

        if not post_id:
            logger.debug(f"Post {post.get('id')} has no platform post_id, skipping.")
            continue

        if platform == "facebook":
            if fb_done:
                stats["facebook"]["skipped"] += 1
                logger.debug(f"Debounce: skipping Facebook post {post_id}")
                continue
            fb_done = True
            logger.info(f"Fetching Facebook insights for post {post_id}...")
            if dry_run:
                logger.info(f"  [DRY RUN] Would fetch FB insights for {post_id}")
                stats["facebook"]["fetched"] += 1
                stats["total"] += 1
                continue
            try:
                metrics = fetch_facebook_insights(post_id)
                if metrics:
                    db.upsert_social_post_metrics(
                        post_id=post_id,
                        platform="facebook",
                        metrics=metrics,
                        posted_at=posted_at,
                    )
                    stats["facebook"]["fetched"] += 1
                    stats["total"] += 1
                    logger.info(f"  ✓ Saved FB metrics for {post_id}: {metrics}")
                else:
                    logger.warning(f"  ✗ No FB metrics returned for {post_id}")
                    stats["facebook"]["errors"] += 1
            except Exception as e:
                logger.error(f"  ✗ Error fetching FB insights for {post_id}: {e}")
                stats["facebook"]["errors"] += 1

        elif platform == "tiktok":
            if tt_done:
                stats["tiktok"]["skipped"] += 1
                logger.debug(f"Debounce: skipping TikTok post {post_id}")
                continue
            tt_done = True
            logger.info(f"Fetching TikTok insights for post {post_id}...")
            if dry_run:
                logger.info(f"  [DRY RUN] Would fetch TT insights for {post_id}")
                stats["tiktok"]["fetched"] += 1
                stats["total"] += 1
                continue
            try:
                metrics = fetch_tiktok_insights(post_id)
                if metrics:
                    db.upsert_social_post_metrics(
                        post_id=post_id,
                        platform="tiktok",
                        metrics=metrics,
                        posted_at=posted_at,
                    )
                    stats["tiktok"]["fetched"] += 1
                    stats["total"] += 1
                    logger.info(f"  ✓ Saved TT metrics for {post_id}: {metrics}")
                else:
                    logger.warning(f"  ✗ No TT metrics returned for {post_id}")
                    stats["tiktok"]["errors"] += 1
            except Exception as e:
                logger.error(f"  ✗ Error fetching TT insights for {post_id}: {e}")
                stats["tiktok"]["errors"] += 1
        else:
            logger.warning(f"Unknown platform '{platform}' for post {post_id}, skipping.")

    logger.info(f"Heartbeat insights complete: {stats['total']} fetched, "
                f"FB={stats['facebook']['fetched']} "
                f"TT={stats['tiktok']['fetched']}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poll social posts for insights.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would be done without making API calls")
    args = parser.parse_args()

    stats = run(dry_run=args.dry_run)
    sys.exit(0 if stats["total"] > 0 else 0)
