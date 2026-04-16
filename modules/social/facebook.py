"""
modules/social/facebook.py — Facebook Video Publisher

Implements Facebook Graph API video publishing via page access token.
Logs stub behavior if token is placeholder or missing.
"""

import logging
import requests
from pathlib import Path
from typing import Optional

from modules.pipeline.models import SocialPlatformConfig

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v19.0"


class FacebookPublisher:
    """Publish videos to Facebook Page via Graph API."""

    def __init__(self, config: SocialPlatformConfig):
        self.config = config
        self.page_id = config.page_id or ""
        self.access_token = config.access_token or ""
        self.auto_publish = config.auto_publish
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
        """Upload and publish a video to Facebook Page."""
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
            file_size = video_path.stat().st_size

            # Step 1: Initialize upload session
            init_url = f"{GRAPH_API}/{self.page_id}/videos"
            init_data = {
                "access_token": self.access_token,
                "upload_phase": "start",
                "file_size": file_size,
            }
            init_resp = self._retry_request("POST", init_url, data=init_data)
            if not init_resp:
                return None

            upload_session_id = init_resp.get("upload_session_id")
            video_id = init_resp.get("video_id")
            logger.info(f"   Upload session: {upload_session_id}, video_id: {video_id}")

            # Step 2: Transfer video data (chunked upload)
            transfer_url = f"{GRAPH_API}/{self.page_id}/videos"
            chunk_size = 5 * 1024 * 1024  # 5MB chunks

            with open(video_path, "rb") as f:
                offset = 0
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    chunk_data = {
                        "access_token": self.access_token,
                        "upload_session_id": upload_session_id,
                        "upload_phase": "transfer",
                        "start_offset": offset,
                    }
                    # For chunk upload, send as form data with the chunk
                    transfer_resp = self._retry_request(
                        "POST", transfer_url, data=chunk_data
                    )
                    if not transfer_resp:
                        return None

                    offset += len(chunk)
                    logger.info(f"   Transferred {offset}/{file_size} bytes")

            # Step 3: Finish upload session
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
                        json_data: dict = None, files: dict = None,
                        retries: int = 3) -> Optional[dict]:
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
            else:
                if data:
                    kwargs["data"] = data
                if json_data:
                    kwargs["json"] = json_data
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

    def get_post_insights(self, post_id: str) -> Optional[dict]:
        """"Fetch insights metrics for a Facebook video post.

        Args:
            post_id: The Facebook video post ID.
        Returns:
            Dict with: reach, impressions, engagement, clicks, video_views.
            Returns None on failure or if not configured.
        """
        if not self.is_configured:
            logger.warning("⚠️  Facebook: not configured — cannot fetch insights")
            return None

        metrics = "reach,impressions,engagement,clicks,video_views"
        url = f"{GRAPH_API}/{post_id}/insights"
        params = {
            "access_token": self.access_token,
            "metric": metrics,
        }

        try:
            resp = self._retry_request("GET", url, data=params)
            if not resp:
                return None

            result = {
                "reach": 0,
                "impressions": 0,
                "engagement": 0,
                "clicks": 0,
                "video_views": 0,
            }

            data = resp.get("data", [])
            for item in data:
                name = item.get("name", "")
                value = item.get("values", [{}])[0].get("value", 0)
                if name == "reach":
                    result["reach"] = value
                elif name == "impressions":
                    result["impressions"] = value
                elif name == "engagement":
                    result["engagement"] = value
                elif name == "clicks":
                    result["clicks"] = value
                elif name == "video_views":
                    result["video_views"] = value

            logger.info(f"📊 Facebook insights for {post_id}: reach={result['reach']}, "
                        f"impressions={result['impressions']}, views={result['video_views']}")
            return result

        except Exception as e:
            logger.error(f"❌ Facebook insights error for {post_id}: {e}")
            return None