"""
tests/test_models.py — Tests for SocialPlatformConfig auth fields and SocialConfig.load()
"""

import tempfile
import yaml
from pathlib import Path

import pytest


def test_social_platform_config_has_auth_fields():
    """SocialPlatformConfig must have access_token, page_id, advertiser_id, account_id as proper fields."""
    from modules.pipeline.models import SocialPlatformConfig

    cfg = SocialPlatformConfig(
        page_id="PAGE123",
        page_name="Test Page",
        access_token="token_abc",
        account_id="ACCT456",
        account_name="@test",
        auto_publish=True,
    )

    assert hasattr(cfg, "page_id"), "SocialPlatformConfig missing page_id field"
    assert hasattr(cfg, "access_token"), "SocialPlatformConfig missing access_token field"
    assert hasattr(cfg, "advertiser_id"), "SocialPlatformConfig missing advertiser_id field"
    assert hasattr(cfg, "account_id"), "SocialPlatformConfig missing account_id field"

    assert cfg.page_id == "PAGE123"
    assert cfg.access_token == "token_abc"
    assert cfg.advertiser_id is None  # not set in this test
    assert cfg.account_id == "ACCT456"


def test_social_config_loads_auth_from_yaml():
    """SocialConfig should load page_id and access_token from the YAML config file."""
    from modules.pipeline.models import SocialConfig

    # Create temp config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({
            "facebook": {
                "page_id": "FB_PAGE_789",
                "page_name": "TestPage",
                "access_token": "fb_token_xyz",
                "auto_publish": True,
            },
            "tiktok": {
                "advertiser_id": "TT_ADV_123",
                "account_id": "TT_ACC_456",
                "account_name": "@testaccount",
                "auto_publish": True,
            }
        }, f)
        config_path = f.name

    try:
        config = SocialConfig.load(config_path)

        assert config.facebook.page_id == "FB_PAGE_789", f"Expected FB page_id, got {config.facebook.page_id}"
        assert config.facebook.access_token == "fb_token_xyz", f"Expected FB access_token, got {config.facebook.access_token}"
        assert config.tiktok.advertiser_id == "TT_ADV_123"
        assert config.tiktok.account_id == "TT_ACC_456"
    finally:
        Path(config_path).unlink()