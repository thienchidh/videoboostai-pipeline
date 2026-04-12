"""
modules/pipeline/publisher.py — Social media publisher wrapper.

Wraps Facebook and TikTok publishers behind a unified interface
compatible with VideoPipelineV3's upload_to_socials() call.
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from modules.social.facebook import FacebookPublisher
from modules.social.tiktok import TikTokPublisher

logger = logging.getLogger(__name__)


class PublishResult:
    """Result object returned by upload_to_socials()."""

    def __init__(self, results: List[Dict[str, Any]]):
        self.results = results

    def summary(self) -> str:
        """Return a human-readable summary of publish results."""
        parts = []
        for r in self.results:
            platform = r.get("platform", "unknown")
            success = r.get("success", False)
            if success:
                parts.append(f"{platform}: OK")
            else:
                parts.append(f"{platform}: FAILED ({r.get('error', 'unknown')})")
        return ", ".join(parts)

    @property
    def success(self) -> bool:
        return all(r.get("success", False) for r in self.results)


class SocialPublisher:
    """Unified social publisher wrapping Facebook and TikTok publishers."""

    def __init__(self, config: dict, dry_run: bool = False,
                 video_run_id: str = None):
        self.config = config or {}
        self.dry_run = dry_run
        self.video_run_id = video_run_id

        # Get social config from channel config
        social_cfg = self.config.get("social", {})
        fb_cfg = social_cfg.get("facebook", {}) if isinstance(social_cfg, dict) else {}
        tt_cfg = social_cfg.get("tiktok", {}) if isinstance(social_cfg, dict) else {}

        self.fb_publisher = FacebookPublisher(config=fb_cfg)
        self.tt_publisher = TikTokPublisher(config=tt_cfg)

    def upload_to_socials(self, video_path: str, script: str = "",
                          word_timestamps: list = None,
                          srt_output_name: str = None) -> PublishResult:
        """
        Upload video to all configured social platforms.

        Args:
            video_path: Path to the final video file
            script: Video script/title for caption
            word_timestamps: Word timestamps for SRT generation (unused for now)
            srt_output_name: Base name for SRT file (unused for now)

        Returns:
            PublishResult with per-platform results
        """
        results = []

        if self.dry_run:
            logger.info("[SOCIAL] Dry-run mode - would upload to:")
            if self.fb_publisher.is_configured:
                logger.info(f"  Facebook: {video_path}")
            if self.tt_publisher.is_configured:
                logger.info(f"  TikTok: {video_path}")
            results.append({"platform": "facebook", "success": True, "dry_run": True})
            results.append({"platform": "tiktok", "success": True, "dry_run": True})
            return PublishResult(results)

        # Facebook
        if self.fb_publisher.is_configured:
            fb_result = self.fb_publisher.publish(
                video_path=video_path,
                title=script[:255] if script else "Video from NangSuatThongMinh",
                description=script or "",
            )
            results.append({
                "platform": "facebook",
                "success": fb_result is not None,
                "post_url": fb_result,
            })
        else:
            results.append({"platform": "facebook", "success": False, "error": "not configured"})

        # TikTok
        if self.tt_publisher.is_configured:
            tt_result = self.tt_publisher.publish(
                video_path=video_path,
                title=script[:100] if script else "Video from NangSuatThongMinh",
                description=script or "",
            )
            results.append({
                "platform": "tiktok",
                "success": tt_result is not None,
                "post_url": tt_result,
            })
        else:
            results.append({"platform": "tiktok", "success": False, "error": "not configured"})

        return PublishResult(results)


def get_publisher(dry_run: bool = False, video_run_id: str = None,
                  config: dict = None) -> SocialPublisher:
    """
    Factory function to create a SocialPublisher.

    Args:
        dry_run: If True, simulate uploads without actually posting
        video_run_id: Video run ID for logging/tracking
        config: Full pipeline config dict (should contain 'social' key)

    Returns:
        SocialPublisher instance
    """
    return SocialPublisher(config=config, dry_run=dry_run, video_run_id=video_run_id)
