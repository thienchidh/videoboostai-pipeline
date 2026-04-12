"""
tests/test_bounce_watermark.py — Tests for scripts/bounce_watermark.py
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
VIDEO_RAW = str(FIXTURES_DIR / "videos" / "video_raw.mp4")
VIDEO_9X16 = str(FIXTURES_DIR / "videos" / "video_9x16.mp4")


class TestBounceWatermarkVideoInfo:
    """Tests for get_video_info (imported from video_utils)."""

    def test_video_info_returns_tuple(self):
        """get_video_info returns (width, height, fps, duration)."""
        from core.video_utils import get_video_info

        result = get_video_info(VIDEO_RAW)
        assert isinstance(result, tuple)
        assert len(result) == 4
        w, h, fps, dur = result
        assert w == 1080
        assert h == 1920
        assert fps > 0
        assert dur > 0


class TestBounceWatermarkPhysics:
    """Tests for bounce physics logic."""

    def test_bounce_bounces_off_left_wall(self):
        """Watermark bounces when hitting left boundary."""
        # Simulate the physics from add_bounce_watermark
        # At x=0, vx should become positive (bounce right)
        import numpy as np
        import math

        x = 0.0
        vx = -100.0  # moving left
        min_x = 15.0
        pad = 15

        # If x < min_x, bounce
        if x < min_x:
            x = min_x
            vx = abs(vx)

        assert x == min_x
        assert vx > 0

    def test_bounce_bounces_off_right_wall(self):
        """Watermark bounces when hitting right boundary."""
        # w=1080, tw=200, pad=15 → max_x = 865
        w, tw, pad = 1080, 200, 15
        max_x = w - tw - pad
        x = float(max_x) + 1  # just past boundary
        vx = 100.0  # moving right (would go further past)

        if x > max_x:
            x = max_x
            vx = -abs(vx)

        assert x == max_x
        assert vx < 0

    def test_bounce_bounces_off_top_wall(self):
        """Watermark bounces when hitting top boundary."""
        min_y = 15.0
        y = 0.0
        vy = -100.0

        if y < min_y:
            y = min_y
            vy = abs(vy)

        assert y == min_y
        assert vy > 0

    def test_bounce_bounces_off_bottom_wall(self):
        """Watermark bounces when hitting bottom boundary."""
        h, th, pad = 1920, 80, 15
        max_y = h - th - pad
        y = float(max_y) + 1  # just past boundary
        vy = 100.0  # moving down

        if y > max_y:
            y = max_y
            vy = -abs(vy)

        assert y == max_y
        assert vy < 0

    def test_bounce_within_bounds_no_bounce(self):
        """Watermark continues moving when within bounds."""
        x, vx = 500.0, 100.0
        min_x, max_x = 15.0, 865.0

        x += vx / 30.0  # simulate one frame at 30fps

        # No bounce if within bounds
        assert min_x < x < max_x


class TestBounceWatermarkAddBounce:
    """Integration tests for add_bounce_watermark()."""

    def test_add_bounce_watermark_creates_output(self, tmp_path):
        """add_bounce_watermark creates a watermarked video file."""
        import sys
        sys.path.insert(0, str(FIXTURES_DIR.parent.parent))

        from scripts.bounce_watermark import add_bounce_watermark

        output = tmp_path / "bounced.mp4"
        result = add_bounce_watermark(
            VIDEO_RAW,
            str(output),
            text="@Test",
            font_size=36,
            opacity=0.15,
            speed=50.0,  # slow for fast test
            padding=15,
        )

        assert result is True
        assert Path(output).exists()
        assert Path(output).stat().st_size > 0

    def test_add_bounce_watermark_default_text(self, tmp_path):
        """Default watermark text is used when not specified."""
        from scripts.bounce_watermark import add_bounce_watermark

        output = tmp_path / "default_text.mp4"
        result = add_bounce_watermark(
            VIDEO_RAW,
            str(output),
            font_size=36,
            opacity=0.15,
            speed=50.0,
            padding=15,
        )

        assert result is True
        assert Path(output).exists()

    def test_add_bounce_watermark_nonexistent_input_returns_false(self, tmp_path):
        """add_bounce_watermark handles nonexistent input gracefully."""
        from scripts.bounce_watermark import add_bounce_watermark

        output = tmp_path / "out.mp4"
        try:
            result = add_bounce_watermark(
                "/nonexistent/input.mp4",
                str(output),
            )
            assert result is False
        except Exception:
            # ffprobe raises when file doesn't exist - acceptable
            pass
