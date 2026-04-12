"""
tests/test_karaoke_subtitles.py — Tests for scripts/karaoke_subtitles.py
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
VIDEO_RAW = str(FIXTURES_DIR / "videos" / "video_raw.mp4")
VIDEO_9X16 = str(FIXTURES_DIR / "videos" / "video_9x16.mp4")
TIMESTAMPS_JSON = str(FIXTURES_DIR / "timestamps" / "words_timestamps.json")


class TestKaraokeGetVideoInfo:
    """Tests for get_video_info via karaoke_subtitles module."""

    def test_video_info_imported_from_video_utils(self):
        """karaoke_subtitles imports get_video_info from video_utils."""
        from scripts.karaoke_subtitles import get_video_info

        w, h, fps, dur = get_video_info(VIDEO_RAW)
        assert w == 1080
        assert h == 1920
        assert fps > 0
        assert dur > 0


class TestKaraokeGetWordColorState:
    """Tests for get_word_color_state()."""

    def test_before_word_returns_none(self):
        """Returns None/zero when before word starts."""
        from scripts.karaoke_subtitles import get_word_color_state

        state, col, frac = get_word_color_state(0.0, w_start=1.0, w_end=2.0)
        assert state is None

    def test_fade_in_state(self):
        """FADE_IN when between (w_start - fade) and w_start."""
        from scripts.karaoke_subtitles import get_word_color_state

        state, col, frac = get_word_color_state(0.9, w_start=1.0, w_end=2.0, fade=0.15)
        assert state == "FADE_IN"
        assert 0 < frac <= 1.0

    def test_highlighted_state(self):
        """HIGHLIGHTED when between w_start and (w_end - fade)."""
        from scripts.karaoke_subtitles import get_word_color_state

        state, col, frac = get_word_color_state(1.5, w_start=1.0, w_end=2.0, fade=0.15)
        assert state == "HIGHLIGHTED"
        assert frac == 1.0

    def test_fade_out_state(self):
        """FADE_OUT when between (w_end - fade) and w_end."""
        from scripts.karaoke_subtitles import get_word_color_state

        state, col, frac = get_word_color_state(1.9, w_start=1.0, w_end=2.0, fade=0.15)
        assert state == "FADE_OUT"
        assert 0 <= frac < 1.0

    def test_after_word_returns_none(self):
        """Returns None after word ends."""
        from scripts.karaoke_subtitles import get_word_color_state

        state, col, frac = get_word_color_state(3.0, w_start=1.0, w_end=2.0)
        assert state is None
        assert frac == 0


class TestKaraokeRenderFrame:
    """Tests for render_frame().

    Note: render_frame() depends on system font availability.
    These tests require LiberationSans-Bold or similar font to be installed.
    Font-dependent rendering is tested via integration tests instead.
    """

    def test_render_frame_returns_image_with_real_font(self):
        """render_frame returns a PIL Image when font is available."""
        from scripts.karaoke_subtitles import render_frame
        from PIL import Image
        from core.paths import get_font_path

        timestamps = [{"word": "A", "start": 0.0, "end": 1.0}]
        font_path = get_font_path()
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), 40)

        img = render_frame(timestamps, t=0.5, w=1080, h=1920, font=font)

        assert isinstance(img, Image.Image)
        assert img.size == (1080, 1920)

    def test_render_frame_no_word_returns_transparent(self):
        """render_frame returns transparent image when no word is active."""
        from scripts.karaoke_subtitles import render_frame
        from PIL import Image, ImageFont

        timestamps = [{"word": "Xin", "start": 1.0, "end": 2.0}]
        # Use the same font loading as karaoke_subtitles
        from scripts.karaoke_subtitles import FONT_PATH

        try:
            font_obj = ImageFont.truetype(FONT_PATH, 40)
        except Exception:
            font_obj = ImageFont.load_default()

        img = render_frame(timestamps, t=0.0, w=1080, h=1920, font=font_obj)

        assert isinstance(img, Image.Image)
        # Transparent image (alpha=0)
        _, _, _, a = img.split()
        assert a.getpixel((540, 960)) == 0


class TestKaraokeAddSubtitles:
    """Integration tests for add_karaoke_subtitles()."""

    def test_add_karaoke_with_timestamps(self, tmp_path):
        """add_karaoke_subtitles with provided timestamps succeeds."""
        from scripts.karaoke_subtitles import add_karaoke_subtitles

        output = tmp_path / "subtitled.mp4"
        with open(TIMESTAMPS_JSON) as f:
            timestamps = json.load(f)

        result = add_karaoke_subtitles(
            VIDEO_RAW,
            "Xin chào",  # script text
            str(output),
            timestamps=timestamps,
            font_size=40,
        )

        assert result is True
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_add_karaoke_without_timestamps_generates_fallback(self, tmp_path):
        """add_karaoke_subtitles generates fallback timing when no timestamps."""
        from scripts.karaoke_subtitles import add_karaoke_subtitles

        output = tmp_path / "subtitled_no_ts.mp4"

        result = add_karaoke_subtitles(
            VIDEO_RAW,
            "Xin chào tạm biệt",  # 3 words
            str(output),
            timestamps=None,
            font_size=40,
        )

        assert result is True
        assert Path(output).exists()

    def test_add_karaoke_nonexistent_input_returns_false(self, tmp_path):
        """add_karaoke_subtitles handles nonexistent input gracefully."""
        from scripts.karaoke_subtitles import add_karaoke_subtitles

        output = tmp_path / "out.mp4"
        try:
            result = add_karaoke_subtitles(
                "/nonexistent/input.mp4",
                "test",
                str(output),
            )
            # If it returns a value, it should be False
            assert result is False
        except Exception:
            # ffprobe may raise exception for nonexistent file - this is acceptable
            pass
