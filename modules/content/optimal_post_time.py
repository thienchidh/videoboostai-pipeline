"""
modules/content/optimal_post_time.py — Optimal-post-time engine.

Uses historical A/B caption CTR data to determine the best posting hour for
each platform (facebook / tiktok). Schedules uploads to `scheduled_posts` DB
instead of posting immediately.

Usage:
    engine = OptimalPostTimeEngine()
    best_hour = engine.compute_best_hour("facebook")
    engine.schedule_upload(video_id=run_id, platform="facebook", target_hour=best_hour)
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional

from db import get_session
from modules.pipeline.models import CTRData
import db_models as models

logger = logging.getLogger(__name__)


class OptimalPostTimeEngine:
    """
    Compute best posting hour from A/B caption CTR data and schedule uploads.

    Algorithm:
        1. Collect all ab_caption_tests that have a winner and ctr_a data.
        2. Group by (platform, posted_hour) — hour extracted from posted_at.
        3. Compute average CTR per hour per platform.
        4. Return hour with highest average CTR.
        5. Fall back to defaults if insufficient data (fewer than min_posts).
    """

    # Default posting hours when no historical data is available
    DEFAULT_BEST_HOURS = {
        "facebook": 20,   # 8 PM下班高峰
        "tiktok":  21,   # 9 PM TikTok active hours
        "both":    20,
    }

    def __init__(self, min_ctr_threshold: float = 0.01, min_posts: int = 3):
        """
        Args:
            min_ctr_threshold: minimum CTR (as fraction, e.g. 0.01 = 1%) to consider a post "meaningful"
            min_posts: minimum number of posts with CTR data required to trust an hour's average
        """
        self.min_ctr_threshold = min_ctr_threshold
        self.min_posts = min_posts

    # ── Public API ────────────────────────────────────────────────────────────

    def compute_best_hour(self, platform: str) -> int:
        """
        Compute the best posting hour (0-23) for the given platform.

        Uses A/B caption test CTR data from ab_caption_tests joined with
        social_posts posted_at timestamp.

        Returns:
            int: hour (0-23) with highest average CTR.
            Falls back to DEFAULT_BEST_HOURS if insufficient data.
        """
        platform = self._normalise_platform(platform)
        hourly_ctr = self._get_hourly_ctr(platform)

        if not hourly_ctr:
            logger.warning(
                f"[OptimalPostTime] No CTR data for '{platform}' — "
                f"falling back to default hour {self.DEFAULT_BEST_HOURS[platform]}"
            )
            return self.DEFAULT_BEST_HOURS[platform]

        # Filter hours with enough sample size
        valid_hours = {
            hour: data for hour, data in hourly_ctr.items()
            if data["count"] >= self.min_posts and data["avg_ctr"] >= self.min_ctr_threshold
        }

        if not valid_hours:
            logger.warning(
                f"[OptimalPostTime] Not enough CTR data for '{platform}' "
                f"(need ≥{self.min_posts} posts per hour) — "
                f"falling back to default hour {self.DEFAULT_BEST_HOURS[platform]}"
            )
            return self.DEFAULT_BEST_HOURS[platform]

        best_hour = max(valid_hours, key=lambda h: valid_hours[h]["avg_ctr"])
        best_ctr = valid_hours[best_hour]["avg_ctr"]
        best_count = valid_hours[best_hour]["count"]

        logger.info(
            f"[OptimalPostTime] Best hour for '{platform}': {best_hour:02d}:00 "
            f"(avg CTR={best_ctr:.4f}, n={best_count})"
        )
        return best_hour

    def schedule_upload(
        self,
        video_id: int,
        platform: str,
        target_hour: int,
        caption: str = None,
        video_path: str = None,
    ) -> int:
        """
        Schedule a video upload for a specific hour today.

        Args:
            video_id: video run id (from video_runs.id)
            platform: 'facebook', 'tiktok', or 'both'
            target_hour: hour of day (0-23) to schedule the post
            caption: optional caption override
            video_path: optional video path override

        Returns:
            scheduled_posts.id (int), or 0 on failure.
        """
        platform = self._normalise_platform(platform)
        scheduled_at = self._make_scheduled_datetime(target_hour)

        with get_session() as session:
            existing = session.query(models.ScheduledPost).filter(
                models.ScheduledPost.video_id == video_id,
                models.ScheduledPost.platform == platform,
                models.ScheduledPost.status == "pending",
            ).first()

            if existing:
                existing.scheduled_at = scheduled_at
                if caption:
                    existing.caption = caption
                if video_path:
                    existing.video_path = video_path
                logger.info(
                    f"[OptimalPostTime] Updated existing schedule: "
                    f"video_id={video_id}, platform={platform}, "
                    f"scheduled_at={scheduled_at}"
                )
                session.flush()
                return existing.id

            post = models.ScheduledPost(
                video_id=video_id,
                platform=platform,
                scheduled_at=scheduled_at,
                caption=caption,
                video_path=video_path,
                status="pending",
            )
            session.add(post)
            session.flush()
            logger.info(
                f"[OptimalPostTime] Scheduled: video_id={video_id}, "
                f"platform={platform}, scheduled_at={scheduled_at}"
            )
            return post.id

    def get_scheduled_posts(self, platform: str = None, status: str = None) -> list:
        """Return pending scheduled posts, optionally filtered by platform/status."""
        with get_session() as session:
            query = session.query(models.ScheduledPost)
            if platform:
                query = query.filter(models.ScheduledPost.platform == platform)
            if status:
                query = query.filter(models.ScheduledPost.status == status)
            rows = query.order_by(models.ScheduledPost.scheduled_at).all()
            return [_scheduled_post_to_dict(r) for r in rows]

    def mark_posted(self, schedule_id: int) -> None:
        """Mark a scheduled post as posted."""
        with get_session() as session:
            post = session.query(models.ScheduledPost).filter_by(id=schedule_id).first()
            if post:
                post.status = "posted"
                post.posted_at = datetime.now(timezone.utc)

    def mark_failed(self, schedule_id: int, error: str = None) -> None:
        """Mark a scheduled post as failed."""
        with get_session() as session:
            post = session.query(models.ScheduledPost).filter_by(id=schedule_id).first()
            if post:
                post.status = "failed"
                post.error = error
                post.posted_at = datetime.now(timezone.utc)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_hourly_ctr(self, platform: str) -> dict:
        """
        Query ab_caption_tests + social_posts to build hourly CTR data.

        Returns:
            Dict[hour, {"avg_ctr": float, "count": int, "total_ctr": float}]
        """
        from sqlalchemy import func, extract

        with get_session() as session:
            # Get all A/B tests with winner + CTR data, joined with posted_at from social_posts
            rows = session.query(
                models.ABCaptionTest,
                models.SocialPost.posted_at,
                models.SocialPost.post_id,
            ).join(
                models.SocialPost,
                (models.ABCaptionTest.post_id == models.SocialPost.post_id)
                & (models.ABCaptionTest.platform == models.SocialPost.platform),
            ).filter(
                models.ABCaptionTest.platform == platform,
                models.ABCaptionTest.winner.isnot(None),
                models.ABCaptionTest.ctr_a.isnot(None),
                models.SocialPost.posted_at.isnot(None),
            ).all()

        if not rows:
            return {}

        hourly: dict = {}
        for test, posted_at, post_id in rows:
            if posted_at is None:
                continue

            # Extract hour from posted_at
            posted_dt = posted_at
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=timezone.utc)
            hour = posted_dt.hour

            ctr_data = test.ctr_a
            if not ctr_data:
                continue

            # CTR is stored as a CTRData model or a raw float.
            if isinstance(ctr_data, dict):
                ctr_data = CTRData.model_validate(ctr_data)
            ctr = float(ctr_data.ctr)

            if hour not in hourly:
                hourly[hour] = {"total_ctr": 0.0, "count": 0}
            hourly[hour]["total_ctr"] += ctr
            hourly[hour]["count"] += 1

        # Compute averages
        result = {}
        for hour, data in hourly.items():
            result[hour] = {
                "avg_ctr": data["total_ctr"] / data["count"],
                "count": data["count"],
                "total_ctr": data["total_ctr"],
            }
        return result

    def _normalise_platform(self, platform: str) -> str:
        """Normalise platform string to 'facebook', 'tiktok', or 'both'."""
        p = (platform or "").lower().strip()
        if p in ("fb", "facebook"):
            return "facebook"
        if p in ("tt", "tiktok"):
            return "tiktok"
        return "both"

    def _make_scheduled_datetime(self, target_hour: int) -> datetime:
        """Build a datetime for today at target_hour (in local TZ)."""
        now = datetime.now(timezone.utc)
        scheduled = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        # If target hour already passed today, schedule for tomorrow
        if scheduled <= now:
            scheduled = scheduled.replace(day=now.day + 1)
        return scheduled


def _scheduled_post_to_dict(p: models.ScheduledPost) -> dict:
    return {
        "id": p.id,
        "video_id": p.video_id,
        "platform": p.platform,
        "scheduled_at": p.scheduled_at,
        "caption": p.caption,
        "video_path": p.video_path,
        "status": p.status,
        "error": p.error,
        "posted_at": p.posted_at,
        "created_at": p.created_at,
    }
