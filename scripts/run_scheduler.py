#!/usr/bin/env python3
"""
scripts/run_scheduler.py — Cron script to process due scheduled posts.

Polls the `scheduled_posts` table every 15 minutes (via cron or CronManager)
and triggers social uploads when the scheduled_at time is due.

Usage:
    # Run once (cron-style)
    python scripts/run_scheduler.py

    # Run continuously (daemon mode)
    python scripts/run_scheduler.py --daemon

    # Dry-run
    python scripts/run_scheduler.py --dry-run

    # Platform filter
    python scripts/run_scheduler.py --platform facebook

Python API:
    from scripts.run_scheduler import PostScheduler
    scheduler = PostScheduler()
    results = scheduler.run()   # returns list of result dicts
    scheduler.report_to_telegram(results)
"""

import sys
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


class PostScheduler:
    """
    Poll `scheduled_posts` for due posts and trigger social upload.

    Flow:
        1. Query scheduled_posts where status=pending AND scheduled_at <= now
        2. For each due post:
           a. Load video from DB (video_runs.output_video)
           b. Load channel config for platform social credentials
           c. Upload via SocialPublisher
           d. Update scheduled_posts status → posted / failed
        3. Send Telegram summary
    """

    def __init__(self, platform: str = None, dry_run: bool = False):
        self.platform = platform
        self.dry_run = dry_run
        self.results: List[Dict] = []
        self._publisher = None

    def run(self) -> List[Dict]:
        """Process all due scheduled posts. Returns list of result dicts."""
        self._init_db()
        due_posts = self._get_due_posts()

        if not due_posts:
            logger.info("[Scheduler] No due posts at this time")
            return []

        logger.info(f"[Scheduler] Processing {len(due_posts)} due post(s)")
        for post in due_posts:
            result = self._process_post(post)
            self.results.append(result)

        return self.results

    def report_to_telegram(self, results: List[Dict] = None) -> None:
        """Send summary to Telegram."""
        if results is None:
            results = self.results

        if self.dry_run:
            logger.info("[DRY-RUN] Telegram report skipped")
            return

        if not results:
            return

        ok = [r for r in results if r.get("status") == "posted"]
        failed = [r for r in results if r.get("status") == "failed"]

        lines = ["📅 *Scheduled Post Runner*\n"]
        lines.append(f"Processed: {len(results)} | ✅ {len(ok)} | ❌ {len(failed)}\n")
        for r in results:
            platform = r.get("platform", "?")
            sched_id = r.get("schedule_id")
            status = r.get("status", "?")
            video_path = r.get("video_path", "N/A")
            if status == "posted":
                lines.append(f"✅ [{platform}] schedule#{sched_id} → posted")
            else:
                err = str(r.get("error", ""))[:60]
                lines.append(f"❌ [{platform}] schedule#{sched_id} → {err}")

        msg = "\n".join(lines)
        self._send_telegram(msg)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _init_db(self):
        try:
            from db import init_db_full
            init_db_full()
        except Exception as e:
            logger.warning(f"DB init skipped: {e}")

    def _get_due_posts(self) -> List[Dict]:
        """Fetch due scheduled posts from DB."""
        try:
            from db import get_due_scheduled_posts
            posts = get_due_scheduled_posts()
            if self.platform:
                posts = [p for p in posts if p.get("platform") == self.platform]
            return posts
        except Exception as e:
            logger.error(f"Failed to fetch due posts: {e}")
            return []

    def _process_post(self, post: Dict) -> Dict:
        """Process a single scheduled post."""
        schedule_id = post.get("id")
        video_id = post.get("video_id")
        platform = post.get("platform", "both")
        video_path = post.get("video_path") or post.get("output_video", "")
        caption = post.get("caption") or post.get("run_caption", "")

        logger.info(
            f"  Processing schedule#{schedule_id}: video_id={video_id}, "
            f"platform={platform}, path={Path(video_path).name if video_path else 'N/A'}"
        )

        if not video_path or not Path(video_path).exists():
            error = f"Video file not found: {video_path}"
            logger.warning(f"  {error}")
            self._mark_failed(schedule_id, error)
            return {**post, "schedule_id": schedule_id, "status": "failed", "error": error}

        # Upload to each platform
        post_results = self._upload_to_social(video_path, caption, platform)

        # Determine overall status
        any_success = any(r.get("success") for r in post_results.values())
        if any_success:
            posted_at = datetime.now(timezone.utc)
            self._mark_posted(schedule_id)
            logger.info(f"  ✅ schedule#{schedule_id} posted successfully")
            return {
                **post,
                "schedule_id": schedule_id,
                "status": "posted",
                "posted_at": posted_at,
            }
        else:
            first_error = next(
                (r.get("error", "unknown") for r in post_results.values() if not r.get("success")),
                "all platforms failed",
            )
            self._mark_failed(schedule_id, first_error)
            return {
                **post,
                "schedule_id": schedule_id,
                "status": "failed",
                "error": first_error,
            }

    def _upload_to_social(self, video_path: str, caption: str, platform: str) -> Dict:
        """Upload to social platforms via SocialPublisher."""
        results: Dict = {}
        publisher = self._get_publisher()

        if publisher is None:
            # No publisher — treat as success in dry-run, fail otherwise
            if self.dry_run:
                for p in self._platforms(platform):
                    results[p] = {"success": True, "dry_run": True}
                return results
            for p in self._platforms(platform):
                results[p] = {"success": False, "error": "publisher not configured"}
            return results

        try:
            pr = publisher.upload_to_socials(video_path=video_path, script=caption)
            for r in pr.results:
                p = r.get("platform", "unknown")
                success = r.get("success", False)
                results[p] = {
                    "success": success,
                    "post_url": r.get("post_url", ""),
                    "post_id": r.get("post_id"),
                    "error": r.get("error") if not success else None,
                }
                if success:
                    logger.info(f"  [SOCIAL] {p} posted: {r.get('post_url', '')}")
                else:
                    logger.warning(f"  [SOCIAL] {p} failed: {r.get('error', 'unknown')}")
        except Exception as e:
            logger.error(f"  [SOCIAL] Upload error: {e}")
            for p in self._platforms(platform):
                results[p] = {"success": False, "error": str(e)}

        return results

    def _get_publisher(self):
        """Lazily build SocialPublisher."""
        if self._publisher is not None:
            return self._publisher
        try:
            from modules.pipeline.models import ChannelConfig
            from modules.pipeline.publisher import get_publisher

            channel_id = "nang_suat_thong_minh"
            try:
                channel_cfg = ChannelConfig.load(channel_id)
            except Exception:
                logger.warning(f"Channel config '{channel_id}' not found")
                self._publisher = None
                return None
            if channel_cfg.social is None:
                logger.warning("No social config in channel")
                self._publisher = None
                return None
            self._publisher = get_publisher(social=channel_cfg.social, dry_run=self.dry_run)
            return self._publisher
        except Exception as e:
            logger.warning(f"Failed to init publisher: {e}")
            self._publisher = None
            return None

    def _platforms(self, platform: str) -> List[str]:
        if platform == "both":
            return ["facebook", "tiktok"]
        return [platform]

    def _mark_posted(self, schedule_id: int):
        try:
            from db import update_scheduled_post_status
            update_scheduled_post_status(
                schedule_id,
                status="posted",
                posted_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"  Failed to mark schedule#{schedule_id} posted: {e}")

    def _mark_failed(self, schedule_id: int, error: str):
        try:
            from db import update_scheduled_post_status
            update_scheduled_post_status(
                schedule_id,
                status="failed",
                error=error,
                posted_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"  Failed to mark schedule#{schedule_id} failed: {e}")

    def _send_telegram(self, message: str):
        try:
            from modules.pipeline.models import TechnicalConfig
            tech = TechnicalConfig.load()
            bot_token = tech.telegram.get("bot_token")
            chat_id = tech.telegram.get("chat_id")
            if not bot_token or not chat_id:
                logger.warning("Telegram not configured; printing message")
                print(message)
                return
            import urllib.request, urllib.parse
            encoded = urllib.parse.quote_plus(message)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={encoded}&parse_mode=Markdown"
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("Telegram notification sent")
                else:
                    logger.warning(f"Telegram returned {resp.status}")
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            print(message)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process due scheduled posts from scheduled_posts table"
    )
    parser.add_argument(
        "--platform", choices=["facebook", "tiktok", "both"], default=None,
        help="Filter by platform (default: all)"
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run continuously in a loop (check every 15 minutes)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Process due posts but do not actually upload"
    )
    parser.add_argument(
        "--interval", type=int, default=15,
        help="Check interval in minutes (daemon mode, default: 15)"
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SCHEDULED POST RUNNER — VP-034")
    logger.info("=" * 60)
    logger.info(f"  Platform : {args.platform or 'all'}")
    logger.info(f"  Dry run  : {args.dry_run}")
    logger.info(f"  Daemon   : {args.daemon}")

    if args.daemon:
        interval_sec = args.interval * 60
        logger.info(f"Running daemon mode — checking every {args.interval} minutes")
        while True:
            scheduler = PostScheduler(platform=args.platform, dry_run=args.dry_run)
            results = scheduler.run()
            scheduler.report_to_telegram(results)
            logger.info(f"Sleeping {interval_sec}s until next check...")
            time.sleep(interval_sec)
    else:
        scheduler = PostScheduler(platform=args.platform, dry_run=args.dry_run)
        results = scheduler.run()

        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("SCHEDULER SUMMARY")
        logger.info("=" * 60)
        for r in results:
            sched_id = r.get("schedule_id")
            platform = r.get("platform", "?")
            status = r.get("status", "?")
            if status == "posted":
                logger.info(f"  ✅ schedule#{sched_id} [{platform}] → posted")
            else:
                logger.info(f"  ❌ schedule#{sched_id} [{platform}] → {r.get('error', 'unknown')}")

        scheduler.report_to_telegram(results)
