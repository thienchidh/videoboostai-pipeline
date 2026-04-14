"""
tests/test_subtitle_srt.py — Tests for SRT subtitle generation from word timestamps.
"""

import os
import tempfile

import pytest


def test_generate_srt_from_timestamps():
    """Generate SRT subtitle file from word timestamps."""
    from modules.media.subtitle_srt import generate_srt

    timestamps = [
        {"word": "Xin", "start": 0.0, "end": 0.3},
        {"word": "chào", "start": 0.3, "end": 0.7},
        {"word": "các", "start": 0.7, "end": 0.9},
        {"word": "bạn", "start": 0.9, "end": 1.3},
    ]

    srt_content = generate_srt(timestamps)

    # Check SRT format
    lines = srt_content.strip().split("\n\n")
    assert len(lines) >= 1, f"Should have at least one subtitle entry, got: {srt_content}"

    # Verify first entry format
    first_entry = lines[0]
    assert "00:00:00,000 --> 00:00:00,300" in first_entry, f"First entry missing timing: {first_entry}"
    assert "Xin" in first_entry, f"First entry missing word 'Xin': {first_entry}"


def test_save_srt_creates_file():
    """save_srt should create a file on disk."""
    from modules.media.subtitle_srt import save_srt

    timestamps = [
        {"word": "Test", "start": 0.0, "end": 0.5},
        {"word": "video", "start": 0.5, "end": 1.0},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "subtitles.srt")
        result = save_srt(timestamps, output_path)

        assert os.path.exists(result), f"SRT file was not created at {result}"
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Test" in content
        assert "video" in content