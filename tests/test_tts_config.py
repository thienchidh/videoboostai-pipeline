"""
tests/test_tts_config.py — Tests for TTS config loading

Verifies TTS providers read all settings from TechnicalConfig Pydantic model.
"""

import pytest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path

from modules.media.tts import MiniMaxTTSProvider, EdgeTTSProvider, get_whisper_timestamps
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
        "api_keys": APIKeys(wavespeed="", minimax="test-key", kie_ai="", you_search=""),
        "api_urls": APIURLs(
            wavespeed="",
            minimax_tts="https://api.minimax.io/v1/t2a_v2",
            minimax_image="",
            kie_ai="",
            tiktok="",
            facebook_graph=""
        ),
        "models": GenerationModels(tts="speech-2.1-hd"),
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
            image=GenerationImage(),
            lipsync=GenerationLipsync(),
            seeds=GenerationSeeds(),
        ),
        "storage": storage,
    }
    if overrides:
        defaults.update(overrides)
    return TechnicalConfig(**defaults)


class TestMiniMaxTTSConfig:
    """Tests for MiniMaxTTSProvider config loading."""

    def test_uses_config_url(self):
        """MiniMaxTTSProvider should read base_url from config."""
        tech_config = make_tech_config({
            "api_urls": APIURLs(
                wavespeed="",
                minimax_tts="https://custom.api.minimax.io/v1/t2a_v2",
                minimax_image="",
                kie_ai="",
                tiktok="",
                facebook_graph=""
            ),
        })
        provider = MiniMaxTTSProvider(tech_config)
        assert provider.base_url == "https://custom.api.minimax.io/v1/t2a_v2"

    def test_uses_config_model(self):
        """MiniMaxTTSProvider should read model from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.8-hd",
                    sample_rate=32000,
                    timeout=60,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=128000,
                    format="mp3",
                    channel=1,
                ),
                image=GenerationImage(),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })
        provider = MiniMaxTTSProvider(tech_config)
        assert provider.model == "speech-2.8-hd"

    def test_uses_config_timeout(self):
        """MiniMaxTTSProvider should read timeout from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.8-hd",
                    sample_rate=32000,
                    timeout=120,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=128000,
                    format="mp3",
                    channel=1,
                ),
                image=GenerationImage(),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })
        provider = MiniMaxTTSProvider(tech_config)
        assert provider.timeout == 120

    def test_uses_config_audio_settings(self):
        """TTS audio settings should come from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.8-hd",
                    sample_rate=48000,
                    timeout=60,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=256000,
                    format="mp3",
                    channel=2,
                ),
                image=GenerationImage(),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })
        provider = MiniMaxTTSProvider(tech_config)
        assert provider.sample_rate == 48000
        assert provider.bitrate == 256000
        assert provider.format == "mp3"
        assert provider.channel == 2

    def test_rejects_non_technical_config(self):
        """MiniMaxTTSProvider should raise TypeError when passed MagicMock instead of TechnicalConfig."""
        mock_config = MagicMock()
        with pytest.raises(TypeError) as exc_info:
            MiniMaxTTSProvider(mock_config)
        assert "TechnicalConfig Pydantic model" in str(exc_info.value)

    def test_minimax_tts_generate_calls_correct_api_key(self):
        """MiniMaxTTSProvider.generate should use self._api_key (not self.api_key) in Authorization header."""
        tech_config = make_tech_config()
        provider = MiniMaxTTSProvider(tech_config)

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"base_resp": {"status_code": 0}, "data": {"audio": ""}}
            mock_post.return_value = mock_resp

            provider.generate("test text", "female_voice", 1.0, "/tmp/test.mp3")

            call_headers = mock_post.call_args[1]["headers"]
            assert call_headers["Authorization"] == "Bearer test-key"
            assert not any(k for k in call_headers if "api_key" in k.lower())

    def test_uses_config_temp_dir(self):
        """Should use storage.temp_dir for temp file paths when configured."""
        tech_config = make_tech_config({
            "storage": StorageConfig(
                temp_dir="/custom/temp",
                s3=S3Config(
                    endpoint="https://s3.example.com",
                    access_key="key",
                    secret_key="secret",
                    bucket="bucket",
                    public_url_base="https://s3.example.com/public"
                ),
                database=DatabaseConfig()
            ),
        })
        provider = MiniMaxTTSProvider(tech_config)
        path = provider._get_temp_path("tts_minimax")
        assert path.startswith("/custom/temp")


class TestEdgeTTSConfig:
    """Tests for EdgeTTSProvider config loading."""

    def test_works_without_config(self):
        """EdgeTTSProvider should work without config (backward compat)."""
        provider = EdgeTTSProvider()
        assert provider._config is None

    def test_edge_tts_returns_tuple_without_config(self):
        """EdgeTTSProvider.generate should return tuple even without config."""
        provider = EdgeTTSProvider()

        def _close_coro(coro):
            coro.close()

        with patch("asyncio.set_event_loop_policy"):
            with patch("asyncio.run", side_effect=_close_coro):
                with patch("edge_tts.Communicate") as MockComm:
                    mock_comm = MagicMock()

                    def fake_save(path):
                        Path(path).write_bytes(b"fake audio content" * 100)

                    mock_comm.save = fake_save
                    MockComm.return_value = mock_comm

                    with patch("pathlib.Path.exists", return_value=True):
                        with patch("pathlib.Path.stat", return_value=MagicMock(st_size=10000)):
                            with patch("modules.media.tts.get_whisper_timestamps",
                                       return_value=[{"word": "test", "start": 0.1, "end": 0.5}]):
                                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                                    output_path = f.name

                                result = provider.generate("test text", "female_voice", 1.0, output_path)

                                assert isinstance(result, tuple)


class TestGetWhisperTimestamps:
    """Tests for get_whisper_timestamps config loading."""

    def test_timeout_from_config(self):
        """Should use word_timestamp_timeout from config."""
        tech_config = make_tech_config({
            "generation": GenerationConfig(
                llm=GenerationLLM(),
                tts=GenerationTTS(
                    model="speech-2.8-hd",
                    sample_rate=32000,
                    timeout=60,
                    max_duration=15.0,
                    min_duration=5.0,
                    words_per_second=2.5,
                    bitrate=128000,
                    format="mp3",
                    channel=1,
                    word_timestamp_timeout=180,
                ),
                image=GenerationImage(),
                lipsync=GenerationLipsync(),
                seeds=GenerationSeeds(),
            ),
        })

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", MagicMock()):
                        with patch("json.load", return_value={"segments": []}):
                            result = get_whisper_timestamps("/fake/audio.mp3", config=tech_config)
                            call_kwargs = mock_run.call_args[1]
                            assert call_kwargs["timeout"] == 180

    def test_default_timeout_when_config_missing(self):
        """Should use default timeout of 120 when config doesn't have word_timestamp_timeout."""
        tech_config = make_tech_config()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", MagicMock()):
                        with patch("json.load", return_value={"segments": []}):
                            result = get_whisper_timestamps("/fake/audio.mp3", config=tech_config)
                            call_kwargs = mock_run.call_args[1]
                            assert call_kwargs["timeout"] == 120