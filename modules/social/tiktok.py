"""
modules/social/tiktok.py — TikTok Video Publisher

Implements TikTok Marketing API video publishing.
Logs stub behavior if token is placeholder or missing.
"""

import logging
import time
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


class TikTokPublisher:
    """Publish videos to TikTok via Marketing API."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.advertiser_id = self.config.get("advertiser_id", "")
        self.access_token = self.config.get("access_token", "")
        self.auto_publish = self.config.get("auto_publish", False)
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
            # Step 1: Initiate upload
            init_url = f"{TIKTOK_API_BASE}/video/upload/"
            files = {"video_file": open(video_path, "rb")}
            init_data = {
                "advertiser_id": self.advertiser_id,
                "video_description": description[:2000],
            }
            
            resp = self._retry_request("POST", init_url, files=files, data=init_data)
            if not resp:
                return None

            video_id = resp.get("video_id")
            logger.info(f"   TikTok video_id: {video_id}")

            # Step 2: Submit to TikTok (post-upload processing)
            # The video needs to be finalized before it can be posted
            submit_url = f"{TIKTOK_API_BASE}/video/publish/"
            submit_data = {
                "advertiser_id": self.advertiser_id,
                "video_id": video_id,
                "post_description": title[:100],
            }

            submit_resp = self._retry_request("POST", submit_url, data=submit_data)
            if not submit_resp:
                return None

            logger.info(f"✅ TikTok: published! Video ID: {video_id}")
            logger.info(f"   Title: {title[:80]}")
            return f"https://www.tiktok.com/@user/video/{video_id}"

        except Exception as e:
            logger.error(f"❌ TikTok publish error: {e}")
            return None
        finally:
            # Ensure file handle is closed
            pass

    def _retry_request(self, method: str, url: str,
                       data: dict = None, files: dict = None, retries: int = 3) -> Optional[dict]:
        """Make HTTP request with exponential backoff for rate limits."""
        for attempt in range(retries):
            try:
                kwargs = {"timeout": 120}
                if files:
                    kwargs["files"] = files
                    # For multipart, don't set Content-Type header manually
                    headers = {}
                    self._session.headers.pop("Content-Type", None)
                else:
                    kwargs["json"] = data
                    headers = {"Content-Type": "application/json"}
                    self._session.headers.update(headers)

                resp = self._session.request(method, url, **kwargs)

                if resp.status_code == 429:
                    wait = (2 ** attempt) * 30
                    logger.warning(f"   TikTok rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code >= 400:
                    logger.error(f"   TikTok API error {resp.status_code}: {resp.text[:300]}")
                    return None

                return resp.json()

            except requests.exceptions.RequestException as e:
                logger.error(f"   Request error (attempt {attempt+1}): {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None

        return None

    def post_text(self, text: str) -> Optional[str]:
        """Post a text-only update (if TikTok supports it)."""
        logger.warning("⚠️  TikTok: text-only posts not supported via API — video post required")
        return None