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

        with patch("asyncio.set_event_loop_policy") as mock_set_policy:
            with patch("asyncio.run") as mock_run:
                with patch("asyncio.WindowsProactorEventLoopPolicy", return_value=MagicMock(), create=True):
                    with patch("edge_tts.Communicate") as MockComm:
                        mock_comm = MagicMock()

                        def fake_save(path):
                            Path(path).write_bytes(b"fake audio content" * 100)

                        mock_comm.save = fake_save
                        MockComm.return_value = mock_comm

                        with patch("pathlib.Path.exists", return_value=True):
                            with patch("pathlib.Path.stat", return_value=MagicMock(st_size=10000)):
                                with patch("modules.media.tts.get_whisper_timestamps",
                                           return_value=[{"word": "test", "start": 0.1, "end": 0.5}]) as mock_ts:
                                    # Create a temp output path
                                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                                        output_path = f.name

                                    result = provider.generate("test text", "female_voice", 1.0, output_path)

                                # Result MUST be a tuple
                                assert isinstance(result, tuple), \
                                    f"Expected tuple, got {type(result)}: {result}"

                                path, timestamps = result
                                assert isinstance(path, str), \
                                    f"path should be str, got {type(path)}"
                                assert isinstance(timestamps, list), \
                                    f"timestamps should be list, got {type(timestamps)}"
                                assert len(timestamps) == 1
                                assert timestamps[0]["word"] == "test"

    def test_edge_tts_returns_none_on_error(self):
        """EdgeTTSProvider.generate returns None when edge-tts fails."""
        provider = EdgeTTSProvider()

        with patch("asyncio.set_event_loop_policy") as mock_set_policy:
            with patch("asyncio.run", side_effect=Exception("edge-tts error")):
                result = provider.generate("test text", "female_voice", 1.0, "/tmp/test.mp3")

                # On error should return None (not tuple)
                assert result is None


class TestGetWhisperTimestamps:
    """Tests for get_whisper_timestamps function."""

    def test_returns_none_for_missing_file(self):
        """Returns None if audio file does not exist."""
        result = get_whisper_timestamps("/nonexistent/audio.mp3")
        assert result is None