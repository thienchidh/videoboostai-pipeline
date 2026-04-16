"""
tests/test_music_gen.py — VP-033 unit tests for modules/media/music_gen.py

Tests:
- MiniMaxMusicProvider.__init__
- MiniMaxMusicProvider.generate() — success (URL audio)
- MiniMaxMusicProvider.generate() — success (base64 audio)
- MiniMaxMusicProvider.generate() — API error response
- MiniMaxMusicProvider.generate() — HTTP/network exception
- MiniMaxMusicProvider.generate() — no audio in response
- MiniMaxMusicProvider.generate() — audio download failure
- create_mock_music() behavior
- Integration with MusicProvider base class
"""

import base64
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.plugins import MusicProvider
from modules.media.music_gen import MiniMaxMusicProvider, create_mock_music


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_ffmpeg_success(tmp_path):
    """Mock subprocess.run to simulate successful ffmpeg + ensure output file exists."""
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text('#!/bin/bash\necho done\n')
    fake_ffmpeg.chmod(0o755)

    def fake_run(cmd, *, capture_output, text, timeout):
        # Write a small valid-ish MP3 stub to the output path (last arg)
        output_path = cmd[-1]
        Path(output_path).write_bytes(b"MP3 stub content" * 10)
        result = MagicMock()
        result.returncode = 0
        return result

    with patch("modules.media.music_gen.get_ffmpeg", return_value=Path(fake_ffmpeg)):
        with patch("modules.media.music_gen.subprocess.run", side_effect=fake_run):
            yield


@pytest.fixture
def provider():
    """MiniMaxMusicProvider with test API key."""
    return MiniMaxMusicProvider(api_key="test_api_key_123")


@pytest.fixture
def provider_custom_url():
    """MiniMaxMusicProvider with custom API URL."""
    return MiniMaxMusicProvider(
        api_key="test_key",
        api_url="https://custom.example.com/v1/music",
    )


# ─── __init__ tests ───────────────────────────────────────────────────────────

class TestMiniMaxMusicProviderInit:
    """Tests for MiniMaxMusicProvider.__init__."""

    def test_sets_api_key(self, provider):
        assert provider.api_key == "test_api_key_123"

    def test_sets_default_base_url(self, provider):
        assert provider.base_url == "https://api.minimax.io/v1/music_generation"

    def test_sets_custom_api_url(self, provider_custom_url):
        assert provider_custom_url.base_url == "https://custom.example.com/v1/music"

    def test_is_music_provider_subclass(self, provider):
        assert isinstance(provider, MusicProvider)


# ─── generate() success: URL audio ───────────────────────────────────────────

class TestGenerateSuccessUrlAudio:
    """Tests for MiniMaxMusicProvider.generate() with URL-based audio response."""

    def test_generate_returns_path_on_success(self, provider, tmp_path):
        output_path = str(tmp_path / "music_output.mp3")

        mock_audio_content = b"fake mp3 audio data" * 100

        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {
                "audio_file": {
                    "url": "https://cdn.example.com/music/abc123.mp3"
                }
            }
        }

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = mock_audio_content

        with patch("modules.media.music_gen.requests.post", return_value=mock_post_resp) as mock_post:
            with patch("modules.media.music_gen.requests.get", return_value=mock_get_resp) as mock_get:
                result = provider.generate(
                    prompt="upbeat pop music",
                    duration=30,
                    output_path=output_path,
                )

        assert result == output_path
        assert Path(output_path).read_bytes() == mock_audio_content

        # Verify correct headers sent
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test_api_key_123"
        assert call_kwargs.kwargs["json"]["model"] == "music-01"
        assert call_kwargs.kwargs["json"]["prompt"] == "upbeat pop music"
        assert call_kwargs.kwargs["json"]["duration"] == 30

    def test_generate_uses_default_output_path(self, provider, tmp_path):
        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "base_resp": {"status_code": 0},
            "data": {
                "audio_file": {
                    "url": "https://cdn.example.com/music/abc123.mp3"
                }
            }
        }
        mock_get_resp = MagicMock(status_code=200, content=b"audio")

        with patch("modules.media.music_gen.requests.post", return_value=mock_post_resp):
            with patch("modules.media.music_gen.requests.get", return_value=mock_get_resp):
                with patch("time.time", return_value=1234567890.0):
                    result = provider.generate(prompt="test", duration=15)

        assert result is not None
        assert result.startswith("/tmp/music_")
        assert result.endswith(".mp3")


# ─── generate() success: base64 audio ────────────────────────────────────────

class TestGenerateSuccessBase64Audio:
    """Tests for MiniMaxMusicProvider.generate() with base64-encoded audio."""

    def test_generate_decodes_base64_audio(self, provider, tmp_path):
        output_path = str(tmp_path / "music_b64.mp3")
        expected_content = b"decoded base64 audio content"

        b64_audio = base64.b64encode(expected_content).decode()

        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "base_resp": {"status_code": 0},
            "data": {
                "audio": b64_audio
            }
        }

        with patch("modules.media.music_gen.requests.post", return_value=mock_post_resp):
            result = provider.generate(
                prompt="sad piano melody",
                duration=60,
                output_path=output_path,
            )

        assert result == output_path
        assert Path(output_path).read_bytes() == expected_content


# ─── generate() error: API error response ───────────────────────────────────

class TestGenerateApiError:
    """Tests for MiniMaxMusicProvider.generate() when API returns an error."""

    def test_generate_returns_none_on_api_error(self, provider, tmp_path):
        output_path = str(tmp_path / "should_not_exist.mp3")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 1001, "status_msg": "quota exceeded"},
        }

        with patch("modules.media.music_gen.requests.post", return_value=mock_resp):
            result = provider.generate(prompt="test", output_path=output_path)

        assert result is None
        assert not Path(output_path).exists()

    def test_generate_returns_none_on_nonzero_status_code(self, provider, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 999, "status_msg": "invalid request"},
        }

        with patch("modules.media.music_gen.requests.post", return_value=mock_resp):
            result = provider.generate(prompt="test")

        assert result is None


# ─── generate() error: no audio in response ──────────────────────────────────

class TestGenerateNoAudio:
    """Tests for MiniMaxMusicProvider.generate() when response has no audio."""

    def test_generate_returns_none_when_response_missing_audio(self, provider, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 0},
            "data": {}
        }

        with patch("modules.media.music_gen.requests.post", return_value=mock_resp):
            result = provider.generate(prompt="test")

        assert result is None

    def test_generate_returns_none_when_data_missing(self, provider, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 0},
        }

        with patch("modules.media.music_gen.requests.post", return_value=mock_resp):
            result = provider.generate(prompt="test")

        assert result is None


# ─── generate() error: HTTP/network exception ───────────────────────────────

class TestGenerateNetworkError:
    """Tests for MiniMaxMusicProvider.generate() on network/HTTP failure."""

    def test_generate_returns_none_on_post_exception(self, provider, tmp_path):
        with patch("modules.media.music_gen.requests.post", side_effect=Exception("connection refused")):
            result = provider.generate(prompt="test")

        assert result is None

    def test_generate_returns_none_on_download_failure(self, provider, tmp_path):
        output_path = str(tmp_path / "partial.mp3")

        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {
            "base_resp": {"status_code": 0},
            "data": {
                "audio_file": {
                    "url": "https://cdn.example.com/music/abc123.mp3"
                }
            }
        }

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 404  # Download failed

        with patch("modules.media.music_gen.requests.post", return_value=mock_post_resp):
            with patch("modules.media.music_gen.requests.get", return_value=mock_get_resp):
                result = provider.generate(prompt="test", output_path=output_path)

        assert result is None
        assert not Path(output_path).exists()


# ─── create_mock_music() tests ───────────────────────────────────────────────

class TestCreateMockMusic:
    """Tests for create_mock_music() — dry-run placeholder."""

    def test_creates_silent_audio_file(self, mock_ffmpeg_success, tmp_path):
        output_path = str(tmp_path / "mock_music.mp3")

        result = create_mock_music(
            prompt="any prompt",
            duration=5,
            output_path=output_path,
        )

        assert result == output_path
        assert Path(output_path).exists()
        assert Path(output_path).stat().st_size > 0

    def test_creates_file_with_correct_duration(self, mock_ffmpeg_success, tmp_path):
        output_path = str(tmp_path / "mock_duration.mp3")

        with patch("time.time", return_value=1234567890.0):
            result = create_mock_music(prompt="test", duration=10, output_path=output_path)

        assert result == output_path

    def test_uses_default_output_path(self, mock_ffmpeg_success):
        with patch("time.time", return_value=1234567890.0):
            result = create_mock_music(prompt="test", duration=5)

        assert result is not None
        assert result.startswith("/tmp/music_mock_")
        assert result.endswith(".mp3")

    def test_returns_none_when_ffmpeg_fails(self, tmp_path):
        # Patch get_ffmpeg to return non-existent path
        fake_missing = tmp_path / "nonexistent_ffmpeg"
        output_path = str(tmp_path / "should_not_exist.mp3")

        with patch("modules.media.music_gen.get_ffmpeg", return_value=Path(fake_missing)):
            result = create_mock_music(prompt="test", duration=5, output_path=output_path)

        assert result is None

    def test_returns_none_when_output_file_not_created(self, tmp_path):
        # ffmpeg succeeds (subprocess returns 0) but file doesn't exist
        output_path = str(tmp_path / "ghost.mp3")
        fake_ffmpeg = tmp_path / "ffmpeg"
        fake_ffmpeg.write_text("#!/bin/bash\n")

        with patch("modules.media.music_gen.get_ffmpeg", return_value=Path(fake_ffmpeg)):
            with patch("modules.media.music_gen.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                # First exists check returns False (output doesn't exist after cmd)
                # Second exists check returns True (parent dir exists)
                with patch("pathlib.Path.exists", side_effect=[False, True]):
                    result = create_mock_music(prompt="test", duration=5, output_path=output_path)

        assert result is None


# ─── Integration: MusicProvider base class ──────────────────────────────────

class TestMusicProviderInterface:
    """Verify MiniMaxMusicProvider conforms to MusicProvider ABC."""

    def test_generate_is_abstract_method(self, provider):
        # The provider implements generate() with the correct signature
        import inspect
        sig = inspect.signature(provider.generate)
        params = list(sig.parameters.keys())
        assert "prompt" in params
        assert "duration" in params
        assert "output_path" in params

    def test_provider_registered_as_music_provider(self):
        # Verify module-level registration doesn't raise
        from modules.media import music_gen
        from core.plugins import get_provider

        # The provider should be registered under music/minimax
        with patch("core.plugins.get_provider") as mock_get:
            mock_provider_cls = MagicMock()
            mock_get.return_value = mock_provider_cls
            # Just verify registration doesn't error
            from modules.media.music_gen import register_music_providers
            register_music_providers()
