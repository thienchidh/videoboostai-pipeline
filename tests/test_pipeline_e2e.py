"""
tests/test_pipeline_e2e.py — End-to-end pipeline tests using fixture data.

These tests compose the pipeline using pre-generated fixture files
(TTS audio, images, videos) to test the full pipeline flow without
calling real external APIs.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AUDIO_FILE = str(FIXTURES_DIR / "audio" / "tts_sample.mp3")
IMAGE_FILE = str(FIXTURES_DIR / "images" / "scene_sample.png")
IMAGE_MULTI = str(FIXTURES_DIR / "images" / "scene_multi.png")
VIDEO_RAW = str(FIXTURES_DIR / "videos" / "video_raw.mp4")
VIDEO_9X16 = str(FIXTURES_DIR / "videos" / "video_9x16.mp4")
VIDEO_MULTI = str(FIXTURES_DIR / "videos" / "video_multi_raw.mp4")
TIMESTAMPS_JSON = str(FIXTURES_DIR / "timestamps" / "words_timestamps.json")


E2E_CONFIG = {
    "scenes": [
        {
            "id": 1,
            "script": "Xin chào",
            "characters": ["TestChar"],
            "background": "default",
        },
        {
            "id": 2,
            "script": "Tạm biệt",
            "characters": ["TestChar"],
            "background": "default",
        }
    ],
    "characters": [
        {
            "name": "TestChar",
            "prompt": "3D animated Pixar style character",
            "tts_voice": "female_voice",
            "tts_speed": 1.0,
        }
    ],
    "prompt": {
        "style": "3D animated Pixar Disney style",
        "script_hints": {"default": "warm natural lighting"}
    },
    "tts": {
        "min_duration": 2.0,
        "max_duration": 15.0,
    },
    "models": {"tts": "edge", "image": "minimax"},
    "watermark": {"enable": False},
    "background_music": {"enable": False},
    "subtitle": {"enable": False},
}


class TestPipelineE2EComposition:
    """Test the full pipeline composition using fixtures."""

    def test_concat_two_scene_videos(self, tmp_path):
        """Concatenating two scene videos produces a longer video."""
        from core.video_utils import concat_videos

        # Use the same video twice as a stand-in for 2 scenes
        output = tmp_path / "concat.mp4"
        result = concat_videos([VIDEO_RAW, VIDEO_RAW], str(output))

        assert result is not None
        assert Path(output).exists()

        # Duration should be roughly double (minus overlap)
        from core.video_utils import get_video_duration
        dur = get_video_duration(str(output))
        assert dur > 2.0  # more than one video

    def test_add_karaoke_to_video(self, tmp_path):
        """Adding karaoke subtitles to a video works."""
        from scripts.karaoke_subtitles import add_karaoke_subtitles

        with open(TIMESTAMPS_JSON) as f:
            timestamps = json.load(f)

        output = tmp_path / "subtitled.mp4"
        success = add_karaoke_subtitles(
            VIDEO_9X16,
            "Xin chào",
            str(output),
            timestamps=timestamps,
            font_size=40,
        )

        assert success is True
        assert Path(output).exists()
        assert Path(output).stat().st_size > Path(VIDEO_9X16).stat().st_size

    def test_add_bounce_watermark_to_video(self, tmp_path):
        """Adding bounce watermark to a video works."""
        from scripts.bounce_watermark import add_bounce_watermark

        output = tmp_path / "watermarked.mp4"
        result = add_bounce_watermark(
            VIDEO_9X16,
            str(output),
            text="@TestChannel",
            font_size=36,
            opacity=0.15,
            speed=50.0,
            padding=15,
        )

        assert result is True
        assert Path(output).exists()
        assert Path(output).stat().st_size > Path(VIDEO_9X16).stat().st_size

    def test_full_pipeline_flow_single_scene(self, tmp_path):
        """Simulate full pipeline: TTS → Image → Lipsync → Crop → Concat."""
        from core.video_utils import concat_videos, crop_to_9x16

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        # Step 1: TTS (fixture)
        audio = AUDIO_FILE

        # Step 2: Image (fixture)
        image = IMAGE_FILE

        # Step 3: Lipsync (fixture - or generate with ffmpeg)
        lipsync_out = scene_output / "video_raw.mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", image,
            "-i", audio,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-pix_fmt", "yuv420p",
            str(lipsync_out)
        ], capture_output=True)

        # Step 4: Crop to 9:16
        video_9x16 = scene_output / "video_9x16.mp4"
        cropped = crop_to_9x16(str(lipsync_out), str(video_9x16))

        assert cropped is not None
        assert Path(video_9x16).exists()

        # Verify dimensions
        from core.video_utils import get_video_info
        w, h, fps, dur = get_video_info(str(video_9x16))
        assert w == 1080
        assert h == 1920

    def test_full_pipeline_two_scenes_concatenated(self, tmp_path):
        """Two scenes → concat → final video."""
        from core.video_utils import concat_videos

        # Create two scene videos using fixtures
        scene1 = tmp_path / "scene_1"
        scene2 = tmp_path / "scene_2"
        scene1.mkdir()
        scene2.mkdir()

        # Both scenes: lip sync + crop
        for scene_dir in [scene1, scene2]:
            lipsync = scene_dir / "video_raw.mp4"
            cropped = scene_dir / "video_9x16.mp4"
            subprocess.run([
                "ffmpeg", "-y",
                "-loop", "1", "-i", IMAGE_FILE,
                "-i", AUDIO_FILE,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-shortest", "-pix_fmt", "yuv420p",
                str(lipsync)
            ], capture_output=True)
            from core.video_utils import crop_to_9x16
            crop_to_9x16(str(lipsync), str(cropped))

        # Concat
        concat_output = tmp_path / "concat.mp4"
        result = concat_videos(
            [str(scene1 / "video_9x16.mp4"), str(scene2 / "video_9x16.mp4")],
            str(concat_output)
        )

        assert result is not None
        assert Path(concat_output).exists()

        # Duration should be sum of both scenes
        from core.video_utils import get_video_duration
        dur = get_video_duration(str(concat_output))
        assert dur > 3.0  # each scene ~3s, so total > 3s

    def test_pipeline_with_watermark_and_subtitles(self, tmp_path):
        """Full pipeline: scenes → concat → watermark → subtitles."""
        from scripts.karaoke_subtitles import add_karaoke_subtitles
        from scripts.bounce_watermark import add_bounce_watermark
        from core.video_utils import concat_videos, crop_to_9x16

        # Scene 1
        scene1 = tmp_path / "scene_1"
        scene1.mkdir()
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", IMAGE_FILE,
            "-i", AUDIO_FILE,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-shortest", "-pix_fmt", "yuv420p",
            str(scene1 / "video_raw.mp4")
        ], capture_output=True)
        crop_to_9x16(str(scene1 / "video_raw.mp4"), str(scene1 / "video_9x16.mp4"))

        # Concat
        concat = tmp_path / "concat.mp4"
        concat_videos([str(scene1 / "video_9x16.mp4")], str(concat))

        # Add watermark
        watermarked = tmp_path / "watermarked.mp4"
        add_bounce_watermark(str(concat), str(watermarked),
                            text="@Test", font_size=36, opacity=0.15,
                            speed=50.0, padding=15)

        # Add subtitles
        with open(TIMESTAMPS_JSON) as f:
            timestamps = json.load(f)

        final = tmp_path / "final.mp4"
        add_karaoke_subtitles(str(watermarked), "Xin chào", str(final),
                             timestamps=timestamps, font_size=40)

        assert Path(final).exists()
        assert Path(final).stat().st_size > Path(watermarked).stat().st_size


class TestPipelinePluginsIntegration:
    """Test that PluginRegistry providers are wired correctly."""

    def setup_method(self):
        # Import provider modules to trigger PluginRegistry registration
        from modules.media import tts, image_gen, lipsync  # noqa: F401

    def test_tts_provider_edge_registered(self):
        """EdgeTTSProvider is registered in PluginRegistry."""
        from core.plugins import get_provider

        cls = get_provider("tts", "edge")
        assert cls is not None

    def test_tts_provider_minimax_registered(self):
        """MiniMaxTTSProvider is registered in PluginRegistry."""
        from core.plugins import get_provider

        cls = get_provider("tts", "minimax")
        assert cls is not None

    def test_image_provider_minimax_registered(self):
        """MiniMaxImageProvider is registered in PluginRegistry."""
        from core.plugins import get_provider

        cls = get_provider("image", "minimax")
        assert cls is not None

    def test_lipsync_provider_kieai_registered(self):
        """KieAIInfinitalkProvider is registered in PluginRegistry."""
        from core.plugins import get_provider

        cls = get_provider("lipsync", "kieai")
        assert cls is not None

    def test_unknown_provider_returns_none(self):
        """get_provider returns None for unknown provider."""
        from core.plugins import get_provider

        cls = get_provider("tts", "nonexistent_tts")
        assert cls is None
