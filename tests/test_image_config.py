"""tests/test_image_config.py — Image provider config tests."""

import pytest
from unittest.mock import MagicMock
from modules.media.image_gen import (
    MiniMaxImageProvider,
    WaveSpeedImageProvider,
    KieImageProvider,
)
from modules.pipeline.exceptions import ConfigMissingKeyError


class TestMiniMaxImageConfig:
    """Tests for MiniMaxImageProvider config loading."""

    def test_uses_config_url(self):
        """MiniMaxImageProvider should read base_url from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_image": "https://custom.image.api.io",
            "api.keys.minimax": "test-key",
            "generation.image.timeout": 120,
            "generation.image.model": "image-01",
        }.get(key)

        provider = MiniMaxImageProvider(config=mock_config)
        assert provider.base_url == "https://custom.image.api.io"

    def test_uses_config_timeout_and_model(self):
        """MiniMaxImageProvider should read timeout and model from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_image": "https://api.minimax.io/v1/image_generation",
            "api.keys.minimax": "test-key",
            "generation.image.timeout": 90,
            "generation.image.model": "image-01",
        }.get(key)

        provider = MiniMaxImageProvider(config=mock_config)
        assert provider.timeout == 90
        assert provider.model == "image-01"

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api.urls.minimax_image is missing."""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxImageProvider(config=mock_config)
        assert "api.urls.minimax_image" in str(exc_info.value)

    def test_raises_error_when_api_key_missing(self):
        """Should raise ConfigMissingKeyError when api.keys.minimax is missing."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_image": "https://api.minimax.io/v1/image_generation",
        }.get(key)

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxImageProvider(config=mock_config)
        assert "api.keys.minimax" in str(exc_info.value)


class TestWaveSpeedImageConfig:
    """Tests for WaveSpeedImageProvider config loading."""

    def test_uses_config_url(self):
        """WaveSpeedImageProvider should read base_url from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.wavespeed": "https://custom.wavespeed.io",
            "api.keys.wavespeed": "test-key",
            "generation.image.timeout": 120,
            "generation.image.poll_interval": 5,
            "generation.image.max_polls": 24,
        }.get(key)

        provider = WaveSpeedImageProvider(config=mock_config)
        assert provider.base_url == "https://custom.wavespeed.io"

    def test_uses_config_poll_settings(self):
        """WaveSpeedImageProvider should read poll_interval and max_polls from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.wavespeed": "https://api.wavespeed.ai",
            "api.keys.wavespeed": "test-key",
            "generation.image.timeout": 120,
            "generation.image.poll_interval": 10,
            "generation.image.max_polls": 48,
        }.get(key)

        provider = WaveSpeedImageProvider(config=mock_config)
        assert provider.poll_interval == 10
        assert provider.max_polls == 48

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api.urls.wavespeed is missing."""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            WaveSpeedImageProvider(config=mock_config)
        assert "api.urls.wavespeed" in str(exc_info.value)


class TestKieImageConfig:
    """Tests for KieImageProvider config loading."""

    def test_uses_config_url(self):
        """KieImageProvider should read base_url from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.kie_ai": "https://custom.kie.ai/api/v1",
            "api.keys.kie_ai": "test-key",
            "generation.image.timeout": 120,
            "generation.image.poll_interval": 5,
            "generation.image.max_polls": 24,
        }.get(key)

        provider = KieImageProvider(config=mock_config)
        assert provider.base_url == "https://custom.kie.ai/api/v1"

    def test_uses_config_poll_settings(self):
        """KieImageProvider should read poll_interval and max_polls from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.kie_ai": "https://api.kie.ai/api/v1",
            "api.keys.kie_ai": "test-key",
            "generation.image.timeout": 120,
            "generation.image.poll_interval": 8,
            "generation.image.max_polls": 36,
        }.get(key)

        provider = KieImageProvider(config=mock_config)
        assert provider.poll_interval == 8
        assert provider.max_polls == 36

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api.urls.kie_ai is missing."""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            KieImageProvider(config=mock_config)
        assert "api.urls.kie_ai" in str(exc_info.value)

    def test_raises_error_when_api_key_missing(self):
        """Should raise ConfigMissingKeyError when api.keys.kie_ai is missing."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.kie_ai": "https://api.kie.ai/api/v1",
        }.get(key)

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            KieImageProvider(config=mock_config)
        assert "api.keys.kie_ai" in str(exc_info.value)