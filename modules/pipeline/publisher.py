"""
modules/pipeline/publisher.py — Social media publisher wrapper.

Wraps Facebook and TikTok publishers behind a unified interface
compatible with VideoPipelineV3's upload_to_socials() call.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from modules.social.facebook import FacebookPublisher
from modules.social.tiktok import TikTokPublisher
from modules.pipeline.models import SocialConfig

logger = logging.getLogger(__name__)


class VideoValidationError(Exception):
    """Raised when video quality validation fails."""
    pass


def validate_video_quality(video_path: str) -> tuple[bool, str]:
    """
    Validate that a video file meets quality standards for social upload.

    Checks:
        1. File exists and size > 0
        2. ffprobe reports a valid video stream
        3. Has readable frames (ffmpeg -vframes 1 on a temp file)

    Args:
        video_path: Path to the video file to validate

    Returns:
        (True, "") on success, (False, reason) on failure
    """
    path = Path(video_path)

    # Check 1: File exists and size > 0
    if not path.exists():
        return False, f"File does not exist: {video_path}"
    if path.stat().st_size == 0:
        return False, f"File is empty: {video_path}"

    # Check 2: ffprobe — valid video stream
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, f"ffprobe failed: {result.stderr.strip()}"
        if "streams" not in result.stdout or not result.stdout.strip():
            return False, "ffprobe returned no video streams"
    except subprocess.TimeoutExpired:
        return False, "ffprobe timed out"
    except FileNotFoundError:
        logger.warning("ffprobe not found — skipping video stream validation")

    # Check 3: ffmpeg -vframes 1 — readable frames
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
            tmp_path = tmp.name
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(path),
                "-vframes", "1",
                "-q:v", "2",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return False, f"ffmpeg frame extraction failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "ffmpeg frame extraction timed out"
    except FileNotFoundError:
        logger.warning("ffmpeg not found — skipping frame readability validation")

    return True, ""


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

    def __init__(self, social: SocialConfig, dry_run: bool = False,
                 video_run_id: str = None):
        self.dry_run = dry_run
        self.video_run_id = video_run_id
        self.fb_publisher = FacebookPublisher(config=social.facebook)
        self.tt_publisher = TikTokPublisher(config=social.tiktok)

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

        # Validate video quality before attempting upload
        valid, reason = validate_video_quality(video_path)
        if not valid:
            logger.error(f"❌ Video quality validation failed — skipping social upload: {reason}")
            results.append({
                "platform": "facebook",
                "success": False,
                "error": f"video validation failed: {reason}",
            })
            results.append({
                "platform": "tiktok",
                "success": False,
                "error": f"video validation failed: {reason}",
            })
            return PublishResult(results)

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


def get_publisher(social: SocialConfig, dry_run: bool = False,
                  video_run_id: str = None) -> SocialPublisher:
    """
    Factory function to create a SocialPublisher.

    Args:
        social: SocialConfig with facebook and tiktok platform configs
        dry_run: If True, simulate uploads without actually posting
        video_run_id: Video run ID for logging/tracking

    Returns:
        SocialPublisher instance
    """
    return SocialPublisher(social=social, dry_run=dry_run, video_run_id=video_run_id)
