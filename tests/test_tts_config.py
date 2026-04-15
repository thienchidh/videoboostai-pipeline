"""
tests/test_tts_config.py — Tests for TTS config loading

Verifies TTS providers read all settings from config and raise
ConfigMissingKeyError when required keys are missing.
"""

import pytest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path

from modules.media.tts import MiniMaxTTSProvider, EdgeTTSProvider, get_whisper_timestamps
from modules.pipeline.exceptions import ConfigMissingKeyError


class TestMiniMaxTTSConfig:
    """Tests for MiniMaxTTSProvider config loading."""

    def test_uses_config_url(self):
        """MiniMaxTTSProvider should read base_url from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://custom.api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.model": "speech-2.8-hd",
            "generation.tts.timeout": 60,
            "generation.tts.sample_rate": 32000,
            "generation.tts.bitrate": 128000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 1,
        }.get(key)

        provider = MiniMaxTTSProvider(mock_config)
        assert provider.base_url == "https://custom.api.minimax.io/v1/t2a_v2"

    def test_uses_config_model(self):
        """MiniMaxTTSProvider should read model from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.model": "speech-2.1-hd",
            "generation.tts.timeout": 60,
            "generation.tts.sample_rate": 32000,
            "generation.tts.bitrate": 128000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 1,
        }.get(key)

        provider = MiniMaxTTSProvider(mock_config)
        assert provider.model == "speech-2.1-hd"

    def test_uses_config_timeout(self):
        """MiniMaxTTSProvider should read timeout from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.model": "speech-2.8-hd",
            "generation.tts.timeout": 120,
            "generation.tts.sample_rate": 32000,
            "generation.tts.bitrate": 128000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 1,
        }.get(key)

        provider = MiniMaxTTSProvider(mock_config)
        assert provider.timeout == 120

    def test_uses_config_audio_settings(self):
        """TTS audio settings should come from config."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.model": "speech-2.8-hd",
            "generation.tts.timeout": 60,
            "generation.tts.sample_rate": 48000,
            "generation.tts.bitrate": 256000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 2,
        }.get(key)

        provider = MiniMaxTTSProvider(mock_config)
        assert provider.sample_rate == 48000
        assert provider.bitrate == 256000
        assert provider.format == "mp3"
        assert provider.channel == 2

    def test_raises_error_when_url_missing(self):
        """Should raise ConfigMissingKeyError when api.urls.minimax_tts is missing."""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxTTSProvider(mock_config)
        assert "api.urls.minimax_tts" in str(exc_info.value)

    def test_raises_error_when_api_key_missing(self):
        """Should raise ConfigMissingKeyError when api.keys.minimax is missing."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
        }.get(key)

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxTTSProvider(mock_config)
        assert "api.keys.minimax" in str(exc_info.value)

    def test_raises_error_when_model_missing(self):
        """Should raise ConfigMissingKeyError when generation.tts.model is missing."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.timeout": 60,
            "generation.tts.sample_rate": 32000,
            "generation.tts.bitrate": 128000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 1,
        }.get(key)

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxTTSProvider(mock_config)
        assert "generation.tts.model" in str(exc_info.value)

    def test_raises_error_when_sample_rate_missing(self):
        """Should raise ConfigMissingKeyError when generation.tts.sample_rate is missing."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.model": "speech-2.8-hd",
            "generation.tts.timeout": 60,
            "generation.tts.bitrate": 128000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 1,
        }.get(key)

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            MiniMaxTTSProvider(mock_config)
        assert "generation.tts.sample_rate" in str(exc_info.value)

    def test_uses_config_temp_dir(self):
        """Should use storage.temp_dir for temp file paths when configured."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "api.urls.minimax_tts": "https://api.minimax.io/v1/t2a_v2",
            "api.keys.minimax": "test-key",
            "generation.tts.model": "speech-2.8-hd",
            "generation.tts.timeout": 60,
            "generation.tts.sample_rate": 32000,
            "generation.tts.bitrate": 128000,
            "generation.tts.format": "mp3",
            "generation.tts.channel": 1,
            "storage.temp_dir": "/custom/temp",
        }.get(key)

        provider = MiniMaxTTSProvider(mock_config)
        path = provider._get_temp_path("tts_minimax")
        assert path.startswith("/custom/temp")


class TestEdgeTTSConfig:
    """Tests for EdgeTTSProvider config loading."""

    def test_raises_error_when_model_missing_from_config(self):
        """Should raise ConfigMissingKeyError when generation.tts.model is missing."""
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "generation.tts.timeout": 60,
        }.get(key)

        with pytest.raises(ConfigMissingKeyError) as exc_info:
            EdgeTTSProvider(mock_config)
        assert "generation.tts.model" in str(exc_info.value)

    def test_works_without_config(self):
        """EdgeTTSProvider should work without config (backward compat)."""
        provider = EdgeTTSProvider()
        assert provider._config is None

    def test_edge_tts_returns_tuple_without_config(self):
        """EdgeTTSProvider.generate should return tuple even without config."""
        provider = EdgeTTSProvider()

        with patch("asyncio.set_event_loop_policy"):
            with patch("asyncio.run"):
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
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda key: {
            "generation.tts.word_timestamp_timeout": 180,
        }.get(key)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", MagicMock()):
                        with patch("json.load", return_value={"segments": []}):
                            result = get_whisper_timestamps("/fake/audio.mp3", config=mock_config)
                            # Should have been called with timeout=180
                            call_kwargs = mock_run.call_args[1]
                            assert call_kwargs["timeout"] == 180

    def test_default_timeout_when_config_missing(self):
        """Should use default timeout of 120 when config doesn't have word_timestamp_timeout."""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", MagicMock()):
                        with patch("json.load", return_value={"segments": []}):
                            result = get_whisper_timestamps("/fake/audio.mp3", config=mock_config)
                            call_kwargs = mock_run.call_args[1]
                            assert call_kwargs["timeout"] == 120