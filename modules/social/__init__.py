"""
modules/social/__init__.py — Social media publishing

Provides:
- FacebookPublisher: publish video to Facebook via Graph API
- TikTokPublisher: publish video to TikTok via Marketing API

Both skip actual API calls when tokens are placeholder/missing.
"""

from modules.social.facebook import FacebookPublisher
from modules.social.tiktok import TikTokPublisher

__all__ = ["FacebookPublisher", "TikTokPublisher"]