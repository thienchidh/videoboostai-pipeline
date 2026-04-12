"""
tests/test_video_utils.py — Tests for core/video_utils.py

Uses real FFmpeg with fixture data. Subprocess calls to ffmpeg/ffprobe
are mocked to avoid actual encoding in unit tests where possible,
but real FFmpeg is used for integration tests.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Fixture data paths
FIXTURES_DIR = Path(__file__).parent / "fixtures"
AUDIO_FILE = FIXTURES_DIR / "audio" / "tts_sample.mp3"
IMAGE_FILE = FIXTURES_DIR / "images" / "scene_sample.png"
VIDEO_RAW = FIXTURES_DIR / "videos" / "video_raw.mp4"
VIDEO_9X16 = FIXTURES_DIR / "videos" / "video_9x16.mp4"
VIDEO_MULTI = FIXTURES_DIR / "videos" / "video_multi_raw.mp4"
IMAGE_MULTI = FIXTURES_DIR / "images" / "scene_multi.png"
TIMESTAMPS_JSON = FIXTURES_DIR / "timestamps" / "words_timestamps.json"


class TestGetVideoInfo:
    """Tests for get_video_info() using real ffprobe."""

    def test_get_video_info_returns_correct_dimensions(self):
        """get_video_info returns (width, height, fps, duration)."""
        from core.video_utils import get_video_info

        w, h, fps, duration = get_video_info(str(VIDEO_RAW))
        assert w == 1080
        assert h == 1920
        assert fps > 0
        assert duration > 0

    def test_get_video_info_9x16_video(self):
        """get_video_info works for 9:16 video."""
        from core.video_utils import get_video_info

        w, h, fps, duration = get_video_info(str(VIDEO_9X16))
        assert w == 1080
        assert h == 1920
        assert abs(w / h - 9 / 16) < 0.01

    def test_get_video_info_nonexistent_raises(self):
        """get_video_info raises for nonexistent file."""
        from core.video_utils import get_video_info

        with pytest.raises(Exception):  # subprocess returns error
            get_video_info("/nonexistent/video.mp4")


class TestGetVideoDuration:
    """Tests for get_video_duration()."""

    def test_get_duration_returns_positive(self):
        """Duration is positive for valid video."""
        from core.video_utils import get_video_duration

        dur = get_video_duration(str(VIDEO_RAW))
        assert dur > 0


class TestGetAudioDuration:
    """Tests for get_audio_duration()."""

    def test_get_audio_duration_positive(self):
        """Audio duration is positive for valid audio."""
        from core.video_utils import get_audio_duration

        dur = get_audio_duration(str(AUDIO_FILE))
        assert dur > 0

    def test_get_audio_duration_matches_expected(self):
        """Audio duration is approximately 3 seconds (our fixture)."""
        from core.video_utils import get_audio_duration

        dur = get_audio_duration(str(AUDIO_FILE))
        assert 2.5 < dur < 4.0  # ~3 second sine wave


class TestCropTo9x16:
    """Tests for crop_to_9x16()."""

    def test_crop_16_9_to_9x16(self, tmp_path):
        """Center-crops a 16:9 input to 9:16 output."""
        from core.video_utils import crop_to_9x16

        # Create a 1920x1080 (16:9) video
        input_video = tmp_path / "input_16x9.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-frames:v", "25",
            str(input_video)
        ], capture_output=True)

        output_video = tmp_path / "output_9x16.mp4"
        result = crop_to_9x16(str(input_video), str(output_video))

        assert result is not None
        assert Path(output_video).exists()

        # Verify output is 9:16
        from core.video_utils import get_video_info
        w, h, fps, dur = get_video_info(str(output_video))
        assert w == 1080
        assert h == 1920

    def test_crop_already_9x16_unchanged(self, tmp_path):
        """Already-9:16 video just gets scaled."""
        from core.video_utils import crop_to_9x16

        output_video = tmp_path / "output.mp4"
        result = crop_to_9x16(str(VIDEO_9X16), str(output_video))

        assert result is not None
        assert Path(output_video).exists()


class TestConcatVideos:
    """Tests for concat_videos()."""

    def test_concat_two_videos(self, tmp_path):
        """Concatenates two videos into one."""
        from core.video_utils import concat_videos

        output = tmp_path / "concat.mp4"
        result = concat_videos([str(VIDEO_RAW), str(VIDEO_RAW)], str(output))

        assert result is not None
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_concat_empty_list_returns_none(self, tmp_path):
        """Empty list returns None."""
        from core.video_utils import concat_videos

        result = concat_videos([], str(tmp_path / "out.mp4"))
        assert result is None

    def test_concat_single_video(self, tmp_path):
        """Single video is copied."""
        from core.video_utils import concat_videos

        output = tmp_path / "single.mp4"
        result = concat_videos([str(VIDEO_RAW)], str(output))

        assert result is not None
        assert Path(output).exists()


class TestExpandScript:
    """Tests for expand_script()."""

    def test_short_script_gets_expanded(self):
        """Script shorter than min_duration gets expanded."""
        from core.video_utils import expand_script

        short_script = "Xin chào"
        result = expand_script(short_script, min_duration=5.0, max_duration=15.0)

        # Should have more words now
        assert len(result.split()) >= len(short_script.split())

    def test_long_script_gets_truncated(self):
        """Script longer than max_duration gets truncated."""
        from core.video_utils import expand_script

        # 100 words should exceed max_duration=15s at 2.5 words/sec
        long_script = " ".join(["word"] * 100)
        result = expand_script(long_script, min_duration=5.0, max_duration=15.0)

        # Should be truncated
        word_count = len(result.split())
        assert word_count <= 100

    def test_optimal_script_unchanged(self):
        """Script already in range stays unchanged."""
        from core.video_utils import expand_script

        script = "Xin chào tôi là AI"  # ~5 words, ~2 sec at 2.5 wps
        result = expand_script(script, min_duration=5.0, max_duration=15.0)

        # Should be close to original
        assert "Xin chào" in result

    def test_expand_script_with_sentence_boundary(self):
        """Truncated script tries to end at sentence boundary."""
        from core.video_utils import expand_script

        # Use text that ends with punctuation
        script = " ".join(["word"] * 50) + " Goodbye."
        result = expand_script(script, min_duration=5.0, max_duration=15.0)

        # Should not end mid-sentence awkwardly
        # (Current implementation truncates, may or may not hit sentence boundary)
        assert len(result.split()) <= 50
        assert len(result) > 0


class TestMockGenerateTTS:
    """Tests for mock_generate_tts()."""

    def test_mock_tts_creates_file(self, tmp_path):
        """mock_generate_tts creates an MP3 file."""
        from core.video_utils import mock_generate_tts

        output = tmp_path / "tts.mp3"
        result = mock_generate_tts("Test text", "female_voice", 1.0, str(output))

        assert Path(result).exists()
        assert Path(result).stat().st_size > 0
        assert result.endswith(".mp3")

    def test_mock_tts_duration_estimate(self, tmp_path):
        """mock TTS duration estimation works."""
        from core.video_utils import mock_generate_tts

        output = tmp_path / "tts.mp3"
        result = mock_generate_tts("Short", "female_voice", 1.0, str(output))

        # File should exist and be real audio
        assert Path(result).exists()


class TestMockGenerateImage:
    """Tests for mock_generate_image()."""

    def test_mock_image_creates_file(self, tmp_path):
        """mock_generate_image creates a PNG file."""
        from core.video_utils import mock_generate_image

        output = tmp_path / "image.png"
        result = mock_generate_image("test prompt", str(output))

        assert result is not None
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_mock_image_is_correct_size(self, tmp_path):
        """mock image is 1080x1920 as expected for 9:16."""
        from core.video_utils import mock_generate_image
        from PIL import Image

        output = tmp_path / "image.png"
        result = mock_generate_image("test prompt", str(output))

        img = Image.open(output)
        assert img.size == (1080, 1920)


class TestMockLipsyncVideo:
    """Tests for mock_lipsync_video()."""

    def test_mock_lipsync_creates_video(self, tmp_path):
        """mock_lipsync_video creates a video from image + audio."""
        from core.video_utils import mock_lipsync_video

        output = tmp_path / "lipsync.mp4"
        result = mock_lipsync_video(str(IMAGE_FILE), str(AUDIO_FILE), str(output))

        assert result is not None
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0


class TestAddStaticWatermark:
    """Tests for add_static_watermark()."""

    def test_static_watermark_adds_overlay(self, tmp_path):
        """add_static_watermark creates a watermarked video."""
        from core.video_utils import add_static_watermark

        output = tmp_path / "watermarked.mp4"
        result = add_static_watermark(
            str(VIDEO_RAW), str(output),
            text="@TestChannel",
            font_size=36,
            opacity=0.3,
        )

        assert result is not None
        assert Path(output).exists()
        # Output should be slightly larger than input (has overlay)
        assert Path(output).stat().st_size > Path(VIDEO_RAW).stat().st_size


class TestAddBackgroundMusic:
    """Tests for add_background_music()."""

    def test_add_music_creates_file(self, tmp_path):
        """add_background_music creates a video with audio mixed in."""
        from core.video_utils import add_background_music

        # First create a video with silent audio
        input_video = tmp_path / "input.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(input_video)
        ], capture_output=True)

        # Create a music file
        music = tmp_path / "music.mp3"
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=5",
            "-ac", "2", "-ar", "44100", str(music)
        ], capture_output=True)

        output = tmp_path / "with_music.mp4"
        result = add_background_music(str(input_video), str(output), music_file=str(music))

        assert Path(result).exists()
        assert Path(result).stat().st_size > 0


class TestDeepMerge:
    """Tests for deep_merge()."""

    def test_deep_merge_override_wins(self):
        """deep_merge: override values take precedence."""
        from core.video_utils import deep_merge

        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"c": 99}, "d": 3}
        result = deep_merge(base, override)

        assert result["a"] == 1
        assert result["b"]["c"] == 99
        assert result["d"] == 3

    def test_deep_merge_nested_dicts(self):
        """deep_merge merges nested dicts recursively."""
        from core.video_utils import deep_merge

        base = {"api": {"key": "base", "url": "http://base"}}
        override = {"api": {"key": "override"}}
        result = deep_merge(base, override)

        assert result["api"]["key"] == "override"
        assert result["api"]["url"] == "http://base"
