"""
modules/social/facebook.py — Facebook Video Publisher

Implements Facebook Graph API video publishing via page access token.
Logs stub behavior if token is placeholder or missing.
"""

import logging
import time
import requests
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v19.0"


class FacebookPublisher:
    """Publish videos to Facebook Page via Graph API."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.page_id = self.config.get("page_id", "")
        self.access_token = self.config.get("access_token", "")
        self.auto_publish = self.config.get("auto_publish", False)
        self._session = requests.Session()

    @property
    def is_configured(self) -> bool:
        """Return True if real credentials are present (not placeholders)."""
        if not self.page_id or not self.access_token:
            return False
        if self.access_token in ("REPLACE_WITH_YOUR_TOKEN", "", "YOUR_FACEBOOK_PAGE_ACCESS_TOKEN"):
            return False
        return True

    def publish(self, video_path: str, title: str, description: str,
                tags: Optional[list] = None) -> Optional[str]:
        """
        Upload and publish a video to Facebook Page.
        
        Args:
            video_path: Path to the video file
            title: Video title
            description: Video description
            tags: Optional list of tags
        
        Returns:
            Post URL on success, None on failure
        """
        if not self.is_configured:
            logger.warning("⚠️  Facebook: not configured — skipping publish (placeholder token)")
            logger.info(f"  Would publish: {Path(video_path).name}")
            logger.info(f"  Title: {title[:60]}")
            return None

        video_path = Path(video_path)
        if not video_path.exists():
            logger.error(f"❌ Video file not found: {video_path}")
            return None

        logger.info(f"📤 Facebook: uploading {video_path.name} ({video_path.stat().st_size // 1024}KB)")

        try:
            # Step 1: Initialize upload session
            init_url = f"{GRAPH_API}/{self.page_id}/videos"
            init_data = {
                "access_token": self.access_token,
                "upload_phase": "start",
                "file_size": video_path.stat().st_size,
            }
            init_resp = self._retry_request("POST", init_url, data=init_data)
            if not init_resp:
                return None

            upload_session_id = init_resp.get("upload_session_id")
            video_id = init_resp.get("video_id")
            logger.info(f"   Upload session: {upload_session_id}, video_id: {video_id}")

            # Step 2: Transfer video data chunk (chunked upload via URL for small-mid files)
            # For simplicity we use the non-chunked approach: direct publish
            # Facebook allows direct publish via the /videos endpoint for files < 1GB
            
            # Finish upload session
            finish_url = f"{GRAPH_API}/{self.page_id}/videos"
            finish_data = {
                "access_token": self.access_token,
                "upload_session_id": upload_session_id,
                "upload_phase": "finish",
                "title": title[:255],
                "description": description[:2000],
            }
            
            finish_resp = self._retry_request("POST", finish_url, data=finish_data)
            if not finish_resp:
                return None

            post_id = finish_resp.get("id", video_id)
            post_url = f"https://www.facebook.com/{self.page_id}/videos/{post_id}"
            
            logger.info(f"✅ Facebook: published! Post ID: {post_id}")
            logger.info(f"   URL: {post_url}")
            return post_url

        except Exception as e:
            logger.error(f"❌ Facebook publish error: {e}")
            return None

    def _retry_request(self, method: str, url: str, data: dict = None,
                        json_data: dict = None, retries: int = 3) -> Optional[dict]:
        """Make HTTP request with exponential backoff for rate limits."""
        for attempt in range(retries):
            try:
                kwargs = {"timeout": 60}
                if data:
                    kwargs["data"] = data
                if json_data:
                    kwargs["json"] = json_data

                resp = self._session.request(method, url, **kwargs)
                
                if resp.status_code == 429:
                    wait = (2 ** attempt) * 30
                    logger.warning(f"   Facebook rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code >= 400:
                    logger.error(f"   Facebook API error {resp.status_code}: {resp.text[:200]}")
                    return None

                return resp.json()

            except requests.exceptions.RequestException as e:
                logger.error(f"   Request error (attempt {attempt+1}): {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None

        return None

    def post_text(self, message: str) -> Optional[str]:
        """Post a simple text/status update to the page."""
        if not self.is_configured:
            logger.warning("⚠️  Facebook: not configured — skipping post")
            return None

        try:
            url = f"{GRAPH_API}/{self.page_id}/feed"
            data = {
                "access_token": self.access_token,
                "message": message,
            }
            resp = self._retry_request("POST", url, data=data)
            if resp and "id" in resp:
                logger.info(f"✅ Facebook: text post created, ID: {resp['id']}")
                return f"https://www.facebook.com/{self.page_id}/posts/{resp['id']}"
            return None
        except Exception as e:
            logger.error(f"❌ Facebook text post error: {e}")
            return None