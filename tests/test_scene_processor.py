"""
tests/test_scene_processor.py — Tests for scene_processor.py

Uses fixture data for images/audio/videos. Providers are mocked so
no real API calls are made.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Fixture data paths
FIXTURES_DIR = Path(__file__).parent / "fixtures"
AUDIO_FILE = str(FIXTURES_DIR / "audio" / "tts_sample.mp3")
IMAGE_FILE = str(FIXTURES_DIR / "images" / "scene_sample.png")
IMAGE_MULTI = str(FIXTURES_DIR / "images" / "scene_multi.png")
VIDEO_RAW = str(FIXTURES_DIR / "videos" / "video_raw.mp4")
VIDEO_9X16 = str(FIXTURES_DIR / "videos" / "video_9x16.mp4")
VIDEO_MULTI = str(FIXTURES_DIR / "videos" / "video_multi_raw.mp4")
TIMESTAMPS_JSON = str(FIXTURES_DIR / "timestamps" / "words_timestamps.json")


# Minimal config for testing
MINIMAL_CONFIG = {
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
        "script_hints": {
            "default": "warm natural lighting",
            "office": "modern office workspace",
        }
    },
    "tts": {
        "min_duration": 2.0,
        "max_duration": 15.0,
        "words_per_second": 2.5,
    }
}


class TestSceneProcessorHelpers:
    """Tests for SceneProcessor helper methods."""

    def test_get_character_finds_existing(self):
        """get_character returns character dict when found."""
        from modules.pipeline.scene_processor import SceneProcessor

        config = MagicMock()
        config.get = MagicMock(return_value=MINIMAL_CONFIG["characters"])
        processor = SceneProcessor(config, Path(tempfile.mkdtemp()))

        char = processor.get_character("TestChar")
        assert char is not None
        assert char["name"] == "TestChar"
        assert char["tts_voice"] == "female_voice"

    def test_get_character_returns_none_for_missing(self):
        """get_character returns None when character not found."""
        from modules.pipeline.scene_processor import SceneProcessor

        config = MagicMock()
        config.get = MagicMock(return_value=MINIMAL_CONFIG["characters"])
        processor = SceneProcessor(config, Path(tempfile.mkdtemp()))

        char = processor.get_character("NonExistent")
        assert char is None

    def test_build_scene_prompt_includes_style(self):
        """build_scene_prompt includes global style."""
        from modules.pipeline.scene_processor import SceneProcessor

        config = MagicMock()
        config.get = MagicMock(return_value=MINIMAL_CONFIG["prompt"])
        processor = SceneProcessor(config, Path(tempfile.mkdtemp()))

        scene = {"id": 1, "background": "office", "characters": []}
        prompt = processor.build_scene_prompt(scene)

        assert "Pixar" in prompt or "Disney" in prompt

    def test_build_scene_prompt_includes_background_hint(self):
        """build_scene_prompt adds background-specific hint."""
        from modules.pipeline.scene_processor import SceneProcessor

        def config_get(key, default=None):
            if key == "prompt":
                return MINIMAL_CONFIG["prompt"]
            elif key == "tts":
                return MINIMAL_CONFIG["tts"]
            return default

        config = MagicMock()
        config.get = MagicMock(side_effect=config_get)
        processor = SceneProcessor(config, Path(tempfile.mkdtemp()))

        scene = {"id": 1, "background": "office", "characters": []}
        prompt = processor.build_scene_prompt(scene)

        # Should include background hint (office workspace)
        assert len(prompt) > len(MINIMAL_CONFIG["prompt"]["style"])

    def test_build_scene_prompt_includes_char_prompts(self):
        """build_scene_prompt appends character-specific prompts."""
        from modules.pipeline.scene_processor import SceneProcessor

        def config_get(key, default=None):
            if key == "prompt":
                return MINIMAL_CONFIG["prompt"]
            elif key == "characters":
                return MINIMAL_CONFIG["characters"]
            elif key == "tts":
                return MINIMAL_CONFIG["tts"]
            return default

        config = MagicMock()
        config.get = MagicMock(side_effect=config_get)
        processor = SceneProcessor(config, Path(tempfile.mkdtemp()))

        scene = {
            "id": 1,
            "background": "default",
            "characters": ["TestChar"]
        }
        prompt = processor.build_scene_prompt(scene)

        # Should include character-specific prompt
        assert "Pixar" in prompt

    def test_get_tts_config(self):
        """get_tts_config returns tts section from config."""
        from modules.pipeline.scene_processor import SceneProcessor

        config = MagicMock()
        config.get = MagicMock(side_effect=lambda k, d=None: MINIMAL_CONFIG.get(k, d))
        processor = SceneProcessor(config, Path(tempfile.mkdtemp()))

        tts_cfg = processor.get_tts_config()
        assert tts_cfg["max_duration"] == 15.0


class TestSingleCharSceneProcessor:
    """Tests for SingleCharSceneProcessor.process()."""

    def _make_processor(self):
        """Create processor with minimal config."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data=MINIMAL_CONFIG,
        )
        return SingleCharSceneProcessor(config, Path(tempfile.mkdtemp()))

    def test_process_skips_existing_video(self, tmp_path):
        """process skips if video_9x16.mp4 already exists."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        # Pre-create video file
        existing = scene_output / "video_9x16.mp4"
        existing.write_text("fake video")

        # Pre-create timestamps
        ts_file = scene_output / "words_timestamps.json"
        with open(ts_file, "w") as f:
            json.dump([{"word": "Xin", "start": 0, "end": 1}], f)

        config = PipelineConfig(data=MINIMAL_CONFIG)
        processor = SingleCharSceneProcessor(config, tmp_path)

        scene = {"id": 1, "script": "Xin chào", "characters": ["TestChar"]}

        # Mock all provider functions
        mock_tts = MagicMock(return_value=(str(AUDIO_FILE), None))
        mock_img = MagicMock(return_value=IMAGE_FILE)
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0):
            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        # Should return existing without calling providers
        assert video_path == str(existing)
        mock_tts.assert_not_called()

    def test_process_full_flow_calls_all_providers(self, tmp_path):
        """process calls TTS → image → lipsync → crop in sequence."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        config = PipelineConfig(data=MINIMAL_CONFIG)
        processor = SingleCharSceneProcessor(config, tmp_path)

        scene = {"id": 1, "script": "Xin chào", "characters": ["TestChar"]}

        # Track call order
        call_order = []
        def mock_tts(text, voice, speed, output):
            call_order.append("tts")
            shutil.copy(str(AUDIO_FILE), output)
            return str(AUDIO_FILE)

        def mock_img(prompt, output):
            call_order.append("img")
            shutil.copy(IMAGE_FILE, output)
            return output

        def mock_lip(img_path, audio_path, output, scene_id=None, prompt=None):
            call_order.append("lip")
            shutil.copy(str(VIDEO_RAW), output)
            return output

        def mock_crop(input_path, output_path):
            # Actually create the cropped video at the output path
            shutil.copy(str(VIDEO_9X16), output_path)
            return output_path

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0), \
             patch("modules.pipeline.scene_processor.crop_to_9x16", side_effect=mock_crop):

            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is not None
        assert "tts" in call_order
        assert "img" in call_order
        assert "lip" in call_order

    def test_process_validates_duration(self, tmp_path):
        """process returns None if TTS duration exceeds max."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        config = PipelineConfig(data=MINIMAL_CONFIG)
        processor = SingleCharSceneProcessor(config, tmp_path)

        scene = {"id": 1, "script": "Xin chào", "characters": ["TestChar"]}

        # Mock TTS returning valid audio
        mock_tts = MagicMock(return_value=(str(AUDIO_FILE), None))
        mock_img = MagicMock(return_value=IMAGE_FILE)
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        # But duration check says it's too long
        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=99.0):
            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        # Should fail at duration validation
        assert video_path is None

    def test_process_handles_tts_failure(self, tmp_path):
        """process returns None if TTS returns falsy."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        config = PipelineConfig(data=MINIMAL_CONFIG)
        processor = SingleCharSceneProcessor(config, tmp_path)

        scene = {"id": 1, "script": "Xin chào", "characters": ["TestChar"]}

        mock_tts = MagicMock(return_value=(None, None))  # TTS failed
        mock_img = MagicMock(return_value=IMAGE_FILE)
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is None

    def test_process_handles_image_failure(self, tmp_path):
        """process returns None if image gen fails."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        config = PipelineConfig(data=MINIMAL_CONFIG)
        processor = SingleCharSceneProcessor(config, tmp_path)

        scene = {"id": 1, "script": "Xin chào", "characters": ["TestChar"]}

        mock_tts = MagicMock(return_value=(str(AUDIO_FILE), None))
        mock_img = MagicMock(return_value=None)  # Image failed
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0):
            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is None


class TestMultiCharSceneProcessor:
    """Tests for MultiCharSceneProcessor.process()."""

    MULTI_CHAR_CONFIG = {
        "characters": [
            {
                "name": "Char1",
                "prompt": "first character",
                "tts_voice": "female_voice",
                "tts_speed": 1.0,
            },
            {
                "name": "Char2",
                "prompt": "second character",
                "tts_voice": "male-qn-qingse",
                "tts_speed": 1.0,
            }
        ],
        "prompt": {
            "style": "Pixar style",
            "script_hints": {"default": "default"}
        },
        "tts": {
            "min_duration": 2.0,
            "max_duration": 15.0,
            "words_per_second": 2.5,
        }
    }

    def test_multi_process_skips_existing(self, tmp_path):
        """process skips if video_9x16.mp4 exists."""
        from modules.pipeline.scene_processor import MultiCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)
        (scene_output / "video_9x16.mp4").write_text("fake")

        config = PipelineConfig(data=self.MULTI_CHAR_CONFIG)
        processor = MultiCharSceneProcessor(config, tmp_path)

        scene = {
            "id": 1,
            "script": "Xin chào tạm biệt",
            "characters": ["Char1", "Char2"]
        }

        mock_tts = MagicMock()
        mock_img = MagicMock()
        mock_lip = MagicMock()

        video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is not None
        mock_tts.assert_not_called()

    def test_multi_process_calls_tts_for_both_chars(self, tmp_path):
        """process generates TTS for both characters."""
        from modules.pipeline.scene_processor import MultiCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig
        import shutil

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        config = PipelineConfig(data=self.MULTI_CHAR_CONFIG)
        processor = MultiCharSceneProcessor(config, tmp_path)

        scene = {
            "id": 1,
            "script": "Tôi là Char1. Tôi là Char2.",
            "characters": ["Char1", "Char2"]
        }

        tts_calls = []
        def mock_tts(text, voice, speed, output):
            tts_calls.append((text, voice, speed))
            # Write the file so scene_img.exists() check passes
            shutil.copy(str(AUDIO_FILE), output)
            return str(AUDIO_FILE)

        def mock_img(prompt, output):
            # Write the file so image_fn result works
            shutil.copy(IMAGE_MULTI, output)
            return output

        def mock_lip(img, audio, output, scene_id=None, prompt=None):
            shutil.copy(str(VIDEO_MULTI), output)
            return output

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0), \
             patch("modules.pipeline.scene_processor.crop_to_9x16", return_value=str(VIDEO_9X16)), \
             patch("modules.pipeline.scene_processor.concat_videos", return_value=str(VIDEO_9X16)):

            video_path, timestamps = processor.process(
                scene, scene_output, mock_tts, mock_img, mock_lip
            )

        assert video_path is not None
        assert len(tts_calls) == 2  # One per character

    def test_multi_process_missing_character_raises(self, tmp_path):
        """process returns None if a character is not found."""
        from modules.pipeline.scene_processor import MultiCharSceneProcessor
        from modules.pipeline.config_loader import PipelineConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        config = PipelineConfig(data=self.MULTI_CHAR_CONFIG)
        processor = MultiCharSceneProcessor(config, tmp_path)

        scene = {
            "id": 1,
            "script": "Xin chào",
            "characters": ["Char1", "NonExistent"]
        }

        mock_tts = MagicMock()
        mock_img = MagicMock()
        mock_lip = MagicMock()

        video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is None
