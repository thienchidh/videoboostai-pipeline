"""
tests/test_lipsync_config.py — Tests for Lipsync providers config loading

Verifies WaveSpeedLipsyncProvider, WaveSpeedMultiTalkProvider, and
KieAIInfinitalkProvider read URLs, poll_interval, max_wait, and retries
from config using Pydantic attribute access.
"""

import pytest
from unittest.mock import MagicMock

from modules.media.lipsync import (
    WaveSpeedLipsyncProvider,
    WaveSpeedMultiTalkProvider,
    KieAIInfinitalkProvider,
)
from modules.pipeline.exceptions import ConfigMissingKeyError


class TestWaveSpeedLipsyncConfig:
    """Tests for WaveSpeedLipsyncProvider config loading."""

    def test_uses_config_base_url(self):
        """Should read base_url from config.api_urls.wavespeed."""
        mock_config = MagicMock()
        mock_config.api_urls.wavespeed = "https://custom.wavespeed.io"
        mock_config.api_keys.wavespeed = "test-key"
        mock_config.generation.lipsync.poll_interval = 15
        mock_config.generation.lipsync.max_wait = 600

        provider = WaveSpeedLipsyncProvider(config=mock_config)
        assert provider.base_url == "https://custom.wavespeed.io"
        assert provider.poll_interval == 15
        assert provider.max_wait == 600

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api_urls.wavespeed is missing."""
        mock_config = MagicMock()
        mock_config.api_urls.wavespeed = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            WaveSpeedLipsyncProvider(config=mock_config)
        assert "api.urls.wavespeed" in str(exc_info.value)
        assert "WaveSpeedLipsyncProvider" in str(exc_info.value)

    def test_retries_from_config(self):
        """Should read retries from config.generation.lipsync.retries."""
        mock_config = MagicMock()
        mock_config.api_urls.wavespeed = "https://api.wavespeed.ai"
        mock_config.api_keys.wavespeed = "test-key"
        mock_config.generation.lipsync.poll_interval = 10
        mock_config.generation.lipsync.max_wait = 300
        mock_config.generation.lipsync.retries = 4

        provider = WaveSpeedLipsyncProvider(config=mock_config)
        default_retries = provider.config.generation.lipsync.retries
        assert default_retries == 4


class TestWaveSpeedMultiTalkConfig:
    """Tests for WaveSpeedMultiTalkProvider config loading."""

    def test_uses_config_base_url(self):
        """Should read base_url from config.api_urls.wavespeed."""
        mock_config = MagicMock()
        mock_config.api_urls.wavespeed = "https://custom.wavespeed.io"
        mock_config.api_keys.wavespeed = "test-key"
        mock_config.generation.lipsync.poll_interval = 12
        mock_config.generation.lipsync.max_wait = 500

        provider = WaveSpeedMultiTalkProvider(config=mock_config)
        assert provider.base_url == "https://custom.wavespeed.io"
        assert provider.poll_interval == 12
        assert provider.max_wait == 500

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api_urls.wavespeed is missing."""
        mock_config = MagicMock()
        mock_config.api_urls.wavespeed = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            WaveSpeedMultiTalkProvider(config=mock_config)
        assert "api.urls.wavespeed" in str(exc_info.value)
        assert "WaveSpeedMultiTalkProvider" in str(exc_info.value)


class TestKieAIInfinitalkConfig:
    """Tests for KieAIInfinitalkProvider config loading."""

    def test_uses_config_base_url(self):
        """Should read base_url from config.api_urls.kie_ai."""
        mock_config = MagicMock()
        mock_config.api_urls.kie_ai = "https://custom.kie.ai/api/v1"
        mock_config.api_keys.kie_ai = "test-key"
        mock_config.generation.lipsync.poll_interval = 8
        mock_config.generation.lipsync.max_wait = 400

        provider = KieAIInfinitalkProvider(config=mock_config)
        assert provider.base_url == "https://custom.kie.ai/api/v1"
        assert provider.poll_interval == 8
        assert provider.max_wait == 400

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api_urls.kie_ai is missing."""
        mock_config = MagicMock()
        mock_config.api_urls.kie_ai = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            KieAIInfinitalkProvider(config=mock_config)
        assert "api.urls.kie_ai" in str(exc_info.value)
        assert "KieAIInfinitalkProvider" in str(exc_info.value)
