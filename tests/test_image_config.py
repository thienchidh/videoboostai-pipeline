"""tests/test_image_config.py — Image provider config tests."""

import pytest
from unittest.mock import MagicMock
from modules.media.image_gen import (
    MiniMaxImageProvider,
    WaveSpeedImageProvider,
    KieImageProvider,
)
from modules.pipeline.models import (
    TechnicalConfig, GenerationTTS, GenerationLLM, GenerationImage,
    GenerationLipsync, GenerationSeeds, APIKeys, APIURLs, GenerationModels,
    GenerationConfig, StorageConfig, S3Config, DatabaseConfig
)


def make_tech_config(overrides=None):
    """Create a valid TechnicalConfig for testing."""
    storage = StorageConfig(
        s3=S3Config(
            endpoint="https://s3.example.com",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
            public_url_base="https://s3.example.com/public"
        ),
        database=DatabaseConfig()
    )
    defaults = {
        "api_keys": APIKeys(wavespeed="wavespeed-key", minimax="minimax-key", kie_ai="kie-key", you_search=""),
        "api_urls": APIURLs(
            wavespeed="https://api.wavespeed.ai",
            minimax_tts="https://api.minimax.io/v1/t2a_v2",
            minimax_image="https://api.minimax.io/v1/image_generation",
            kie_ai="https://api.kie.ai/api/v1",
            tiktok="",
            facebook_graph=""
        ),
        "models": GenerationModels(tts="speech-2.1-hd", image="minimax"),
        "generation": GenerationConfig(
            llm=GenerationLLM(),
            tts=GenerationTTS(
                model="speech-2.1-hd",
                sample_rate=32000,
                timeout=60,
                max_duration=15.0,
                min_duration=5.0,
                words_per_second=2.5,
                bitrate=128000,
                format="mp3",
                channel=1,
            ),
            image=GenerationImage(
                provider="minimax",
                timeout=120,
                model="image-01",
                poll_interval=5,
                max_polls=24,
            ),
            lipsync=GenerationLipsync(),
            seeds=GenerationSeeds(),
        ),
        "storage": storage,
    }
    if overrides:
        defaults.update(overrides)
    return TechnicalConfig(**defaults)


class TestMiniMaxImageConfig:
    """Tests for MiniMaxImageProvider config loading."""

    def test_uses_config_url(self):
        """MiniMaxImageProvider should read base_url from config."""
        tech_config = make_tech_config({
            "api_urls": APIURLs(
                wavespeed="https://api.wavespeed.ai",
                minimax_tts="https://api.minimax.io/v1/t2a_v2",
                minimax_image="https://custom.image.api.io",
                kie_ai="https://api.kie.ai/api/v1",
                tiktok="",
                facebook_graph=""
            ),
        })
        provider = MiniMaxImageProvider(config=tech_config)
        assert provider.base_url == "https://custom.image.api.io"

    def test_uses_config_timeout_and_model(self):
        """MiniMaxImageProvider should read timeout and model from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.1-hd",
                    sample_rate=32000,
                    timeout=60,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=128000,
                    format="mp3",
                    channel=1,
                ),
                image=GenerationImage(
                    provider="minimax",
                    timeout=90,
                    model="image-01",
                    poll_interval=5,
                    max_polls=24,
                ),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })
        provider = MiniMaxImageProvider(config=tech_config)
        assert provider.timeout == 90
        assert provider.model == "image-01"

    def test_rejects_non_technical_config(self):
        """MiniMaxImageProvider should raise TypeError when passed MagicMock."""
        mock_config = MagicMock()
        with pytest.raises(TypeError) as exc_info:
            MiniMaxImageProvider(config=mock_config)
        assert "TechnicalConfig Pydantic model" in str(exc_info.value)


class TestWaveSpeedImageConfig:
    """Tests for WaveSpeedImageProvider config loading."""

    def test_uses_config_url(self):
        """WaveSpeedImageProvider should read base_url from config."""
        tech_config = make_tech_config({
            "api_urls": APIURLs(
                wavespeed="https://custom.wavespeed.io",
                minimax_tts="https://api.minimax.io/v1/t2a_v2",
                minimax_image="https://api.minimax.io/v1/image_generation",
                kie_ai="https://api.kie.ai/api/v1",
                tiktok="",
                facebook_graph=""
            ),
        })
        provider = WaveSpeedImageProvider(config=tech_config)
        assert provider.base_url == "https://custom.wavespeed.io"

    def test_uses_config_poll_settings(self):
        """WaveSpeedImageProvider should read poll_interval and max_polls from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.1-hd",
                    sample_rate=32000,
                    timeout=60,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=128000,
                    format="mp3",
                    channel=1,
                ),
                image=GenerationImage(
                    provider="wavespeed",
                    timeout=120,
                    model="image-01",
                    poll_interval=10,
                    max_polls=48,
                ),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })
        provider = WaveSpeedImageProvider(config=tech_config)
        assert provider.poll_interval == 10
        assert provider.max_polls == 48

    def test_rejects_non_technical_config(self):
        """WaveSpeedImageProvider should raise TypeError when passed MagicMock."""
        mock_config = MagicMock()
        with pytest.raises(TypeError) as exc_info:
            WaveSpeedImageProvider(config=mock_config)
        assert "TechnicalConfig Pydantic model" in str(exc_info.value)


class TestKieImageConfig:
    """Tests for KieImageProvider config loading."""

    def test_uses_config_url(self):
        """KieImageProvider should read base_url from config."""
        tech_config = make_tech_config({
            "api_urls": APIURLs(
                wavespeed="https://api.wavespeed.ai",
                minimax_tts="https://api.minimax.io/v1/t2a_v2",
                minimax_image="https://api.minimax.io/v1/image_generation",
                kie_ai="https://custom.kie.ai/api/v1",
                tiktok="",
                facebook_graph=""
            ),
        })
        provider = KieImageProvider(config=tech_config)
        assert provider.base_url == "https://custom.kie.ai/api/v1"

    def test_uses_config_poll_settings(self):
        """KieImageProvider should read poll_interval and max_polls from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.1-hd",
                    sample_rate=32000,
                    timeout=60,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=128000,
                    format="mp3",
                    channel=1,
                ),
                image=GenerationImage(
                    provider="kieai",
                    timeout=120,
                    model="z-image",
                    poll_interval=8,
                    max_polls=36,
                ),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })
        provider = KieImageProvider(config=tech_config)
        assert provider.poll_interval == 8
        assert provider.max_polls == 36

    def test_rejects_non_technical_config(self):
        """KieImageProvider should raise TypeError when passed MagicMock."""
        mock_config = MagicMock()
        with pytest.raises(TypeError) as exc_info:
            KieImageProvider(config=mock_config)
        assert "TechnicalConfig Pydantic model" in str(exc_info.value)