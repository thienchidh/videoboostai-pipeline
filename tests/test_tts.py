"""
tests/test_tts.py — Tests for TTS providers

Verifies EdgeTTSProvider and MiniMaxTTSProvider return (path, timestamps) tuple.
"""

import pytest
from unittest.mock import patch, MagicMock
import tempfile
from pathlib import Path

from modules.media.tts import EdgeTTSProvider, get_whisper_timestamps


class TestEdgeTTSProvider:
    """Tests for EdgeTTSProvider."""

    def test_edge_tts_returns_tuple(self):
        """EdgeTTSProvider.generate should return (path, timestamps) tuple."""
        provider = EdgeTTSProvider()

        mock_loop = MagicMock()
        mock_loop.run_until_complete = MagicMock()
        mock_loop.close = MagicMock()

        # Pre-create the output file so the existence/size check passes.
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            output_path = f.name
            f.write(b"fake audio content" * 100)

        with patch("modules.media.tts._create_event_loop", return_value=mock_loop):
            with patch.object(provider, "_get_temp_path", return_value=output_path):
                with patch("modules.media.tts.get_whisper_timestamps",
                           return_value=[{"word": "test", "start": 0.1, "end": 0.5}]):
                    result = provider.generate("test text", "female_voice", 1.0)

                    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}: {result}"
                    path, timestamps = result
                    assert isinstance(path, str)
                    assert isinstance(timestamps, list)
                    assert len(timestamps) == 1
                    assert timestamps[0]["word"] == "test"
                    mock_loop.run_until_complete.assert_called_once()
                    mock_loop.close.assert_called_once()

    def test_edge_tts_returns_none_on_error(self):
        """EdgeTTSProvider.generate returns None when edge-tts fails."""
        provider = EdgeTTSProvider()

        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = Exception("edge-tts error")
        mock_loop.close = MagicMock()

        with patch("modules.media.tts._create_event_loop", return_value=mock_loop):
            with patch.object(provider, "_get_temp_path", return_value="/tmp/test.mp3"):
                result = provider.generate("test text", "female_voice", 1.0, "/tmp/test.mp3")
                assert result is None


class TestGetWhisperTimestamps:
    """Tests for get_whisper_timestamps function."""

    def test_returns_none_for_missing_file(self):
        """Returns None if audio file does not exist."""
        result = get_whisper_timestamps("/nonexistent/audio.mp3")
        assert result is None
