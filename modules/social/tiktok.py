"""
modules/social/tiktok.py — TikTok Video Publisher

Implements TikTok Marketing API video publishing.
Logs stub behavior if token is placeholder or missing.
"""

import logging
import requests
from pathlib import Path
from typing import Optional

from modules.pipeline.models import SocialPlatformConfig

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokPublisher:
    """Publish videos to TikTok via Marketing API."""

    def __init__(self, config: SocialPlatformConfig):
        self.config = config
        self.advertiser_id = config.advertiser_id or ""
        self.access_token = config.access_token or ""
        self.auto_publish = config.auto_publish
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.access_token}" if self.access_token else "",
            "Content-Type": "application/json",
        })

    @property
    def is_configured(self) -> bool:
        """Return True if real credentials are present (not placeholders)."""
        if not self.advertiser_id or not self.access_token:
            return False
        placeholder_tokens = (
            "REPLACE_WITH_YOUR_TIKTOK_TOKEN",
            "",
            "YOUR_TIKTOK_ACCESS_TOKEN",
        )
        if self.access_token in placeholder_tokens:
            return False
        return True

    def publish(self, video_path: str, title: str, description: str,
                tags: Optional[list] = None) -> Optional[str]:
        """
        Upload and publish a video to TikTok.
        
        Args:
            video_path: Path to the video file
            title: Video title (max 100 chars for TikTok)
            description: Video description (hashtags etc.)
            tags: Optional list of hashtags
        
        Returns:
            Video URL on success, None on failure
        """
        if not self.is_configured:
            logger.warning("⚠️  TikTok: not configured — skipping publish (placeholder token)")
            logger.info(f"  Would publish: {Path(video_path).name}")
            logger.info(f"  Title: {title[:60]}")
            return None

        video_path = Path(video_path)
        if not video_path.exists():
            logger.error(f"❌ Video file not found: {video_path}")
            return None

        video_size = video_path.stat().st_size
        logger.info(f"📤 TikTok: uploading {video_path.name} ({video_size // 1024}KB)")

        try:
            # Step 1: Upload video file (uses context manager for file handle)
            upload_url = f"{TIKTOK_API_BASE}/video/upload/"

            with open(video_path, "rb") as video_file:
                upload_data = {
                    "advertiser_id": self.advertiser_id,
                }
                files = {"video_file": video_file}

                resp = self._retry_request("POST", upload_url, files=files, data=upload_data)
                if not resp:
                    return None

                video_id = resp.get("video_id")
                logger.info(f"   TikTok video_id: {video_id}")

            # File handle is now automatically closed after with block

            # Step 2: Publish video with title/description
            publish_url = f"{TIKTOK_API_BASE}/video/publish/"
            publish_data = {
                "advertiser_id": self.advertiser_id,
                "video_id": video_id,
                "post_description": title[:100],
            }

            publish_resp = self._retry_request("POST", publish_url, data=publish_data)
            if not publish_resp:
                return None

            logger.info(f"✅ TikTok: published! Video ID: {video_id}")
            logger.info(f"   Title: {title[:80]}")
            return f"https://www.tiktok.com/@user/video/{video_id}"

        except Exception as e:
            logger.error(f"❌ TikTok publish error: {e}")
            return None

    def _retry_request(self, method: str, url: str,
                       data: dict = None, files: dict = None, retries: int = 3) -> Optional[dict]:
        """Make HTTP request with exponential backoff for rate limits."""
        from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

        @retry(
            stop=stop_after_attempt(retries),
            wait=wait_exponential(multiplier=1, min=1, max=60),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _call():
            kwargs = {"timeout": 120}
            if files:
                kwargs["files"] = files
                headers = {}
                self._session.headers.pop("Content-Type", None)
            else:
                kwargs["json"] = data
                headers = {"Content-Type": "application/json"}
                self._session.headers.update(headers)
            resp = self._session.request(method, url, **kwargs)
            if resp.status_code == 429:
                raise Exception("rate_limit")
            if resp.status_code >= 400:
                raise Exception(f"api_error_{resp.status_code}")
            return resp.json()

        try:
            return _call()
        except Exception:
            return None

    def post_text(self, text: str) -> Optional[str]:
        """Post a text-only update (if TikTok supports it)."""
        logger.warning("⚠️  TikTok: text-only posts not supported via API — video post required")
        return None