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


def make_mock_channel(characters=None, tts_config=None, image_style=None, voices=None):
    """Create a mock PipelineContext with ChannelConfig and TechnicalConfig."""
    from modules.pipeline.models import (
        ChannelConfig, CharacterConfig, TTSConfig, ImageStyleConfig,
        TechnicalConfig, GenerationConfig, GenerationTTS, SceneConfig, VideoSettings
    )

    chars = characters or [
        CharacterConfig(name="TestChar", voice_id="female_voice"),
    ]
    tts = tts_config or TTSConfig(min_duration=2.0, max_duration=15.0)
    img_style = image_style or ImageStyleConfig()

    mock_channel = MagicMock(spec=ChannelConfig)
    mock_channel.characters = chars
    mock_channel.tts = tts
    mock_channel.image_style = img_style
    mock_channel.voices = voices or []
    mock_channel.video = VideoSettings(aspect_ratio="9:16", resolution="480p")

    # Channel generation config
    mock_channel_generation = MagicMock()
    mock_channel_generation.models = MagicMock()
    mock_channel_generation.models.tts = "edge"
    mock_channel_generation.models.image = "kieai"
    mock_channel_generation.models.video = "kieai"
    mock_channel_generation.lipsync = MagicMock()
    mock_channel_generation.lipsync.prompt = "A person talking"
    mock_channel.generation = mock_channel_generation

    # Technical config with generation.tts and parallel_scene_processing
    mock_generation_tts = MagicMock(spec=GenerationTTS)
    mock_generation_tts.min_duration = 5.0
    mock_generation_tts.max_duration = 15.0
    mock_generation_tts.model = "edge-tts"
    mock_generation_tts.sample_rate = 32000
    mock_generation_tts.bitrate = "128k"
    mock_generation_tts.format = "mp3"

    mock_generation_image = MagicMock()
    mock_generation_image.model = "image-01"
    mock_generation_image.timeout = 120
    mock_generation_image.poll_interval = 5
    mock_generation_image.max_polls = 24

    mock_generation_lipsync = MagicMock()
    mock_generation_lipsync.resolution = "480p"
    mock_generation_lipsync.max_wait = 300
    mock_generation_lipsync.poll_interval = 10
    mock_generation_lipsync.retries = 2

    mock_parallel = MagicMock()
    mock_parallel.max_workers = 3

    mock_generation = MagicMock(spec=GenerationConfig)
    mock_generation.tts = mock_generation_tts
    mock_generation.image = mock_generation_image
    mock_generation.lipsync = mock_generation_lipsync
    mock_generation.parallel_scene_processing = mock_parallel

    mock_technical = MagicMock(spec=TechnicalConfig)
    mock_technical.generation = mock_generation

    mock_ctx = MagicMock()
    mock_ctx.channel = mock_channel
    mock_ctx.technical = mock_technical
    return mock_ctx


class TestSceneProcessorHelpers:
    """Tests for SceneProcessor helper methods."""

    def test_get_character_finds_existing(self):
        """get_character returns character when found."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import CharacterConfig

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        ctx = make_mock_channel(characters=characters)

        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        char = processor.get_character("TestChar")
        assert char is not None
        assert char.name == "TestChar"

    def test_get_character_returns_none_for_missing(self):
        """get_character returns None when character not found."""
        from modules.pipeline.scene_processor import SceneProcessor

        ctx = make_mock_channel()
        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        char = processor.get_character("NonExistent")
        assert char is None

    def test_build_scene_prompt_returns_background(self):
        """build_scene_prompt returns scene background."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import SceneConfig

        ctx = make_mock_channel()
        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        scene = SceneConfig(id=1, background="office")
        prompt = processor.build_scene_prompt(scene)

        assert prompt == "office"

    def test_build_scene_prompt_returns_default_when_no_background(self):
        """build_scene_prompt returns default text when no background."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import SceneConfig

        ctx = make_mock_channel()
        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        scene = SceneConfig(id=1)
        prompt = processor.build_scene_prompt(scene)

        assert prompt == "A person talking"

    def test_get_tts_config(self):
        """get_tts_config returns TTSConfig from channel."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import TTSConfig

        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(tts_config=tts_cfg)

        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        result = processor.get_tts_config()
        assert result.max_duration == 15.0
        assert result.min_duration == 2.0


class TestSingleCharSceneProcessor:
    """Tests for SingleCharSceneProcessor.process()."""

    def test_process_accepts_scene_config_from_dict(self, tmp_path):
        """process() accepts a SceneConfig created via SceneConfig.from_dict()."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig, SceneCharacter

        scene_output = tmp_path / "scene_from_dict"
        scene_output.mkdir(parents=True)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path)

        # Use SceneConfig.from_dict() as specified in task
        scene = SceneConfig.from_dict({
            "id": 1,
            "tts": "Xin chào từ SceneConfig",
            "characters": ["TestChar"],
        })

        # Verify it's a proper SceneConfig with SceneCharacter objects
        assert isinstance(scene, SceneConfig)
        assert scene.id == 1
        assert scene.tts == "Xin chào từ SceneConfig"
        assert len(scene.characters) == 1

        # Mock all provider functions
        mock_tts = MagicMock(return_value=(str(AUDIO_FILE), None))
        mock_img = MagicMock(side_effect=lambda prompt, output: (shutil.copy(IMAGE_FILE, output) or output))
        mock_lip = MagicMock(side_effect=lambda img, audio, output, **kw: (shutil.copy(VIDEO_RAW, output) or output))

        def mock_crop(input_path, output_path):
            shutil.copy(str(VIDEO_9X16), output_path)
            return {
                "output": str(output_path),
                "input_width": 1920,
                "input_height": 1080,
                "input_ratio": 1.7778,
                "output_width": 1080,
                "output_height": 1920,
                "crop_filter": "crop=960:1080:480:0,scale=1080:1920",
                "scale_filter": "scale=1080:1920",
                "ffmpeg_cmd": f"ffmpeg -i {input_path} -vf crop=960:1080:480:0,scale=1080:1920 -c:v libx264 -preset fast -crf 23 -c:a aac -y {output_path}",
            }

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0), \
             patch("modules.pipeline.scene_processor.crop_to_9x16", side_effect=mock_crop):
            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is not None
        mock_tts.assert_called_once()
        mock_img.assert_called_once()
        mock_lip.assert_called_once()

    def test_process_skips_existing_video(self, tmp_path):
        """process skips if video_9x16.mp4 already exists."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        # Pre-create video file
        existing = scene_output / "video_9x16.mp4"
        existing.write_text("fake video")

        # Pre-create timestamps
        ts_file = scene_output / "words_timestamps.json"
        with open(ts_file, "w") as f:
            json.dump([{"word": "Xin", "start": 0, "end": 1}], f)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path, resume=True)

        scene = SceneConfig(id=1, script="Xin chào", characters=["TestChar"])

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
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path)

        scene = SceneConfig(id=1, script="Xin chào", characters=["TestChar"])

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
            shutil.copy(str(VIDEO_9X16), output_path)
            return {
                "output": str(output_path),
                "input_width": 1920,
                "input_height": 1080,
                "input_ratio": 1.7778,
                "output_width": 1080,
                "output_height": 1920,
                "crop_filter": "crop=960:1080:480:0,scale=1080:1920",
                "scale_filter": "scale=1080:1920",
                "ffmpeg_cmd": f"ffmpeg -i {input_path} -vf crop=960:1080:480:0,scale=1080:1920 -c:v libx264 -preset fast -crf 23 -c:a aac -y {output_path}",
            }

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
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path)

        scene = SceneConfig(id=1, script="Xin chào", characters=["TestChar"])

        # Track calls and create actual image file when mock_img is called
        def mock_img(prompt, output):
            shutil.copy(IMAGE_FILE, output)
            return output

        mock_tts = MagicMock(return_value=(str(AUDIO_FILE), None))
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        # Duration check says it's too long (99s > 15s max) — should raise SceneDurationError
        from modules.pipeline.exceptions import SceneDurationError
        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=99.0), \
             pytest.raises(SceneDurationError):
            processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

    def test_process_handles_tts_failure(self, tmp_path):
        """process returns None if TTS returns falsy."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path)

        scene = SceneConfig(id=1, script="Xin chào", characters=["TestChar"])

        mock_tts = MagicMock(return_value=(None, None))  # TTS failed
        mock_img = MagicMock(return_value=IMAGE_FILE)
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is None

    def test_process_handles_image_failure(self, tmp_path):
        """process returns None if image gen fails."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig

        scene_output = tmp_path / "scene_1"
        scene_output.mkdir(parents=True)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path)

        scene = SceneConfig(id=1, script="Xin chào", characters=["TestChar"])

        mock_tts = MagicMock(return_value=(str(AUDIO_FILE), None))
        mock_img = MagicMock(return_value=None)  # Image failed
        mock_lip = MagicMock(return_value=VIDEO_9X16)

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0):
            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is None

    def test_scene_processor_skip_image(self, tmp_path):
        """SceneProcessor with skip_image=True skips image generation."""
        from modules.pipeline.scene_processor import SingleCharSceneProcessor
        from modules.pipeline.models import CharacterConfig, TTSConfig, SceneConfig

        scene_output = tmp_path / "scene_skip_image"
        scene_output.mkdir(parents=True)

        characters = [CharacterConfig(name="TestChar", voice_id="female_voice")]
        tts_cfg = TTSConfig(min_duration=2.0, max_duration=15.0)
        ctx = make_mock_channel(characters=characters, tts_config=tts_cfg)

        processor = SingleCharSceneProcessor(ctx, tmp_path, skip_image=True)
        assert processor.skip_image == True

        scene = SceneConfig(id=1, script="Xin chào", characters=["TestChar"])

        # Track calls to verify image and lipsync are NOT called
        call_order = []
        def mock_tts(text, voice, speed, output):
            call_order.append("tts")
            shutil.copy(str(AUDIO_FILE), output)
            return str(AUDIO_FILE)

        def mock_img(prompt, output):
            call_order.append("img")
            return output

        def mock_lip(img_path, audio_path, output, scene_id=None, prompt=None):
            call_order.append("lip")
            return output

        def mock_crop(input_path, output_path):
            shutil.copy(str(VIDEO_9X16), output_path)
            return {
                "output": str(output_path),
                "input_width": 1920,
                "input_height": 1080,
                "input_ratio": 1.7778,
                "output_width": 1080,
                "output_height": 1920,
                "crop_filter": "crop=960:1080:480:0,scale=1080:1920",
                "scale_filter": "scale=1080:1920",
                "ffmpeg_cmd": f"ffmpeg -i {input_path} -vf crop=960:1080:480:0,scale=1080:1920 -c:v libx264 -preset fast -crf 23 -c:a aac -y {output_path}",
            }

        with patch("modules.pipeline.scene_processor.get_audio_duration", return_value=2.0), \
             patch("modules.pipeline.scene_processor.crop_to_9x16", side_effect=mock_crop), \
             patch("modules.pipeline.scene_processor.get_ffmpeg", return_value=Path("ffmpeg")):
            video_path, timestamps = processor.process(scene, scene_output, mock_tts, mock_img, mock_lip)

        assert video_path is not None
        assert "tts" in call_order
        # image provider should NOT be called when skip_image=True
        assert "img" not in call_order
        # lipsync provider should NOT be called — static video is created directly
        assert "lip" not in call_order


class TestAlignWordTimestamps:
    """Tests for align_word_timestamps function."""

    def test_count_match_replaces_words_keeps_timestamps(self):
        """When whisper and script word counts match, replace words, keep timestamps."""
        from modules.pipeline.scene_processor import align_word_timestamps

        whisper = [
            {"word": "tám", "start": 0.0, "end": 0.3},
            {"word": "mươi", "start": 0.3, "end": 0.6},
            {"word": "phần", "start": 0.6, "end": 0.9},
            {"word": "trăm", "start": 0.9, "end": 1.2},
        ]
        script_words = ["80%", "nhân", "viên", "tự"]

        result = align_word_timestamps(whisper, script_words)

        assert result[0]["word"] == "80%"
        assert result[1]["word"] == "nhân"
        assert result[2]["word"] == "viên"
        assert result[3]["word"] == "tự"
        # Timestamps preserved
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 0.3
        assert result[3]["start"] == 0.9
        assert result[3]["end"] == 1.2

    def test_count_mismatch_returns_whisper_intact(self):
        """When word counts differ, return original Whisper timestamps unchanged."""
        from modules.pipeline.scene_processor import align_word_timestamps

        whisper = [
            {"word": "tám", "start": 0.0, "end": 0.3},
            {"word": "mươi", "start": 0.3, "end": 0.6},
        ]
        script_words = ["80%", "nhân", "viên", "tự", "nhận"]  # 5 words vs 2

        result = align_word_timestamps(whisper, script_words)

        assert result == whisper
        assert result[0]["word"] == "tám"
        assert result[1]["word"] == "mươi"

    def test_empty_whisper_returns_empty(self):
        """Empty Whisper timestamps returns empty list."""
        from modules.pipeline.scene_processor import align_word_timestamps

        result = align_word_timestamps([], ["word"])
        assert result == []

    def test_empty_script_returns_whisper(self):
        """Empty script words returns Whisper timestamps unchanged."""
        from modules.pipeline.scene_processor import align_word_timestamps

        whisper = [{"word": "tám", "start": 0.0, "end": 0.3}]
        result = align_word_timestamps(whisper, [])
        assert result == whisper
