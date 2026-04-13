"""
conftest.py — Shared pytest fixtures
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory with minimal config files."""
    tech_dir = tmp_path / "configs" / "technical"
    tech_dir.mkdir(parents=True)

    biz_dir = tmp_path / "configs" / "business"
    biz_dir.mkdir(parents=True)

    # Minimal technical config
    tech_config = {
        "api": {
            "keys": {
                "wavespeed": "test_wavespeed_key",
                "minimax": "test_minimax_key",
            },
            "models": {
                "tts": "edge",
                "image": "minimax",
            },
            "urls": {
                "wavespeed": "https://api.wavespeed.ai",
                "minimax_tts": "https://api.minimax.io/v1/t2a_v2",
                "minimax_image": "https://api.minimax.io/v1/image_generation",
            },
        },
        "storage": {
            "database": {
                "host": "localhost",
                "port": 5432,
                "name": "testdb",
                "user": "testuser",
                "password": "testpass",
            },
            "s3": {
                "endpoint": "https://s3.test.com",
                "access_key": "test_access",
                "secret_key": "test_secret",
                "bucket": "test_bucket",
                "region": "us-east-1",
                "public_url_base": "https://s3.test.com/test_bucket",
            },
        },
    }

    tech_file = tech_dir / "config_technical.yaml"
    tech_file.write_text("api:\n  wavespeed_key: test_wavespeed_key\n  minimax_key: test_minimax_key\n")

    return tmp_path


@pytest.fixture
def sample_business_config():
    """Sample business config for testing."""
    return {
        "title": "Test Video",
        "scenes": [
            {
                "id": 1,
                "script": "Hello world test script",
                "background": "test background",
                "characters": ["TestChar"],
            }
        ],
        "watermark": "@test",
    }


@pytest.fixture
def mock_plugin_registry():
    """Mock PluginRegistry for testing."""
    from unittest.mock import MagicMock
    from core import plugins

    mock_registry = MagicMock()
    mock_registry.get_provider = MagicMock(return_value=MagicMock)
    mock_registry.register_provider = MagicMock()

    with patch.object(plugins, 'get_provider', return_value=MagicMock):
        yield plugins
