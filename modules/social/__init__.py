"""
modules/social/__init__.py — Social media publishing

Provides:
- FacebookPublisher: publish video to Facebook via Graph API (legacy simple publisher)
- FacebookAPIClient: full Graph API v19.0 client with DB credentials, SRT captions,
                     resumable upload, and dry-run mode
- TikTokPublisher: publish video to TikTok via Marketing API

Both Facebook clients skip actual API calls when tokens are placeholder/missing.
"""

from modules.social.facebook import FacebookPublisher
from modules.social.facebook_api import FacebookAPIClient, FacebookUploadResult, get_facebook_client
from modules.social.tiktok import TikTokPublisher

__all__ = [
    "FacebookPublisher",
    "FacebookAPIClient",
    "FacebookUploadResult",
    "get_facebook_client",
    "TikTokPublisher",
]