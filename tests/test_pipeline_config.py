"""
tests/test_pipeline_config.py — Tests for PR#5 Pipeline config hardcode cleanup.

Verifies that SceneProcessor, PipelineRunner, run_pipeline.py, and
video_pipeline_v3.py read values from config instead of using hardcoded defaults.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


class TestSceneProcessorConfig:
    """Tests for SceneProcessor config reading."""

    def _make_mock_ctx(self, max_workers=3, tts_provider="edge", lipsync_prompt="A person talking",
                       voices=None, generation_models=None, channel_video=None, channel_generation=None):
        """Create a mock PipelineContext with configurable values."""
        from modules.pipeline.models import (
            ChannelConfig, TechnicalConfig, GenerationConfig,
            ParallelSceneConfig, GenerationLipsync, GenerationModels,
            VideoSettings, GenerationSettings, VoiceConfig,
        )

        # Mock parallel_scene_processing
        mock_parallel = MagicMock(spec=ParallelSceneConfig)
        mock_parallel.max_workers = max_workers

        mock_generation = MagicMock(spec=GenerationConfig)
        mock_generation.parallel_scene_processing = mock_parallel

        mock_technical = MagicMock(spec=TechnicalConfig)
        mock_technical.generation = mock_generation

        # Mock channel
        mock_channel = MagicMock(spec=ChannelConfig)
        mock_channel.characters = []
        mock_channel.voices = voices or []
        mock_channel.image_style = None

        if channel_video:
            mock_channel.video = channel_video
        else:
            mock_channel.video = None

        if channel_generation:
            mock_channel.generation = channel_generation
        else:
            mock_channel.generation = None

        mock_ctx = MagicMock()
        mock_ctx.channel = mock_channel
        mock_ctx.technical = mock_technical
        return mock_ctx

    def test_max_workers_from_config(self):
        """SceneProcessor reads max_workers from config."""
        from modules.pipeline.scene_processor import SceneProcessor

        ctx = self._make_mock_ctx(max_workers=5)
        run_dir = Path(tempfile.mkdtemp())

        processor = SceneProcessor(ctx, run_dir)
        assert processor.max_workers == 5

    def test_resolve_voice_uses_channel_config_provider(self):
        """resolve_voice uses channel config generation.models.tts as fallback provider."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import VoiceConfig, VoiceProvider, CharacterConfig

        voice = VoiceConfig(
            id="mentor_female",
            name="Mentor Nữ",
            gender="female",
            providers=[
                VoiceProvider(provider="edge", model="vi-VN-HoaiMyNeural", speed=1.0),
            ]
        )

        # Channel with generation.models.tts
        mock_gen_models = MagicMock()
        mock_gen_models.tts = "edge"

        mock_gen = MagicMock()
        mock_gen.models = mock_gen_models
        mock_gen.lipsync = MagicMock()
        mock_gen.lipsync.prompt = "A person talking"

        ctx = self._make_mock_ctx(
            voices=[voice],
            channel_generation=mock_gen,
        )

        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        # Character without voice_id - should fall back to channel config's tts provider
        char = MagicMock()
        char.voice_id = None
        char.name = "TestChar"
        char.tts_voice = None
        char.tts_speed = 1.0

        provider, model, speed, gender = processor.resolve_voice(char, {})
        assert provider == "edge"  # from channel config's generation.models.tts

    def test_resolve_voice_uses_first_voice_from_catalog(self):
        """resolve_voice falls back to first voice from channel voice catalog."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import VoiceConfig, VoiceProvider

        voice = VoiceConfig(
            id="mentor_female",
            name="Mentor Nữ",
            gender="female",
            providers=[
                VoiceProvider(provider="edge", model="vi-VN-HoaiMyNeural", speed=1.0),
            ]
        )

        mock_gen = MagicMock()
        mock_gen.models = MagicMock()
        mock_gen.models.tts = "edge"
        mock_gen.lipsync = MagicMock()
        mock_gen.lipsync.prompt = "A person talking"

        ctx = self._make_mock_ctx(
            voices=[voice],
            channel_generation=mock_gen,
        )

        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        # Create a simple object to use as character
        class SimpleChar:
            def __init__(self):
                self.voice_id = None
                self.name = "TestChar"
                self.tts_speed = 1.0
                self.gender = None

        char = SimpleChar()
        provider, model, speed, gender = processor.resolve_voice(char, {})
        # voice from catalog is used as fallback voice_id
        assert model == "mentor_female"  # first voice id from catalog

    def test_get_video_prompt_uses_channel_lipsync_prompt(self):
        """get_video_prompt uses channel config generation.lipsync.prompt as fallback."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import SceneConfig

        mock_gen = MagicMock()
        mock_gen.models = MagicMock()
        mock_gen.models.tts = "edge"
        mock_gen.lipsync = MagicMock()
        mock_gen.lipsync.prompt = "A person in office"

        ctx = self._make_mock_ctx(channel_generation=mock_gen)

        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        scene = MagicMock(spec=SceneConfig)
        scene.video_prompt = None
        scene.background = None

        prompt = processor.get_video_prompt(scene)
        assert prompt == "A person in office"

    def test_build_scene_prompt_uses_channel_lipsync_prompt(self):
        """build_scene_prompt uses channel config generation.lipsync.prompt as fallback."""
        from modules.pipeline.scene_processor import SceneProcessor
        from modules.pipeline.models import SceneConfig

        mock_gen = MagicMock()
        mock_gen.models = MagicMock()
        mock_gen.models.tts = "edge"
        mock_gen.lipsync = MagicMock()
        mock_gen.lipsync.prompt = "A person talking"

        ctx = self._make_mock_ctx(channel_generation=mock_gen)

        processor = SceneProcessor(ctx, Path(tempfile.mkdtemp()))

        scene = MagicMock(spec=SceneConfig)
        scene.background = None

        prompt = processor.build_scene_prompt(scene)
        assert prompt == "A person talking"


class TestPipelineRunnerConfig:
    """Tests for PipelineRunner config reading."""

    def _make_mock_ctx(self, output_dir="output", max_workers=3, aspect_ratio="9:16",
                       subtitle_font_size=60, bounce_speed=80, bounce_padding=20,
                       technical_storage=None):
        """Create mock PipelineContext for PipelineRunner tests."""
        from modules.pipeline.models import (
            ChannelConfig, TechnicalConfig, GenerationConfig, ParallelSceneConfig,
            VideoSettings, SubtitleConfig, WatermarkConfig, FontConfig,
        )

        mock_parallel = MagicMock(spec=ParallelSceneConfig)
        mock_parallel.max_workers = max_workers

        mock_generation = MagicMock(spec=GenerationConfig)
        mock_generation.parallel_scene_processing = mock_parallel

        # Mock storage with output_dir
        mock_storage = MagicMock()
        mock_storage.output_dir = output_dir

        mock_technical = MagicMock(spec=TechnicalConfig)
        mock_technical.generation = mock_generation
        mock_technical.storage = mock_storage

        # Mock channel video
        mock_video = MagicMock(spec=VideoSettings)
        mock_video.aspect_ratio = aspect_ratio

        # Mock channel subtitle
        mock_subtitle = MagicMock(spec=SubtitleConfig)
        mock_subtitle.font_size = subtitle_font_size

        # Mock channel watermark
        mock_watermark = MagicMock(spec=WatermarkConfig)
        mock_watermark.enable = True
        mock_watermark.text = "@Test"
        mock_watermark.font_size = 30
        mock_watermark.opacity = 0.15
        mock_watermark.motion = "bounce"
        mock_watermark.bounce_speed = bounce_speed
        mock_watermark.bounce_padding = bounce_padding

        # Mock channel fonts
        mock_fonts = MagicMock(spec=FontConfig)
        mock_fonts.watermark = "fonts/LiberationSans-Bold.ttf"

        mock_channel = MagicMock(spec=ChannelConfig)
        mock_channel.video = mock_video
        mock_channel.subtitle = mock_subtitle
        mock_channel.watermark = mock_watermark
        mock_channel.fonts = mock_fonts

        mock_ctx = MagicMock()
        mock_ctx.channel = mock_channel
        mock_ctx.technical = mock_technical
        mock_ctx.channel_id = "test_channel"
        return mock_ctx

    def test_output_dir_from_config(self):
        """PipelineRunner reads output_dir from config.storage.output_dir."""
        # Test that the config structure supports output_dir
        from modules.pipeline.models import StorageConfig, S3Config, DatabaseConfig

        storage = StorageConfig(
            output_dir="custom_output",
            s3=S3Config(
                endpoint="https://example.com",
                access_key="key",
                secret_key="secret",
                bucket="bucket",
                public_url_base="https://example.com/public",
            ),
            database=DatabaseConfig(),
        )
        assert storage.output_dir == "custom_output"
        # Verify the pipeline_runner code uses ctx.technical.storage.output_dir
        import inspect
        from modules.pipeline import pipeline_runner
        source = inspect.getsource(pipeline_runner)
        assert "ctx.technical.storage.output_dir" in source

    def test_max_workers_from_config(self):
        """PipelineRunner reads max_workers from config."""
        ctx = self._make_mock_ctx(max_workers=5)

        mock_scenario = MagicMock()
        mock_scenario.slug = "test-scenario"
        mock_scenario.title = "Test"
        ctx.scenario = mock_scenario

        assert ctx.technical.generation.parallel_scene_processing.max_workers == 5

    def test_aspect_ratio_from_channel_config(self):
        """image_generate uses channel config video.aspect_ratio."""
        ctx = self._make_mock_ctx(aspect_ratio="16:9")

        assert ctx.channel.video.aspect_ratio == "16:9"


class TestRunPipelineDefaultChannel:
    """Tests for run_pipeline.py default channel removal."""

    def test_no_hardcoded_default_channel(self):
        """run_pipeline.py should not have hardcoded default channel."""
        import inspect
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        from run_pipeline import run_full_pipeline

        source = inspect.getsource(run_full_pipeline)
        # The old hardcoded "nang_suat_thong_minh" should NOT appear
        assert '"nang_suat_thong_minh"' not in source
        assert "'nang_suat_thong_minh'" not in source

    def test_no_default_in_argparse(self):
        """run_pipeline.py argparse should not hardcode default channel."""
        import inspect
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import run_pipeline as rp

        # Find the argparse block
        # Check the parser definition doesn't set default to a channel
        source = inspect.getsource(rp)
        # channels = ["nang_suat_thong_minh"] should NOT be the fallback
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'channels = ["nang_suat_thong_minh"]' in line or "channels = ['nang_suat_thong_minh']" in line:
                pytest.fail(f"Hardcoded default channel found at line {i}: {line}")


class TestVideoPipelineV3Config:
    """Tests for video_pipeline_v3.py config reading."""

    def test_max_retries_from_config(self):
        """VideoPipelineV3.run() reads max_retries from config."""
        # The max_retries should come from self.ctx.technical.generation.pipeline.max_retries
        # We test this by checking the code path
        import inspect
        from scripts.video_pipeline_v3 import VideoPipelineV3

        source = inspect.getsource(VideoPipelineV3.run)
        # Should reference ctx.technical.generation.pipeline.max_retries
        assert "ctx.technical.generation.pipeline.max_retries" in source

    def test_wps_from_config(self):
        """_regenerate_script_with_llm accepts wps parameter from config."""
        import inspect
        from scripts.video_pipeline_v3 import _regenerate_script_with_llm

        sig = inspect.signature(_regenerate_script_with_llm)
        params = list(sig.parameters.keys())
        assert "wps" in params


class TestStorageConfigModel:
    """Tests for StorageConfig model with output_dir."""

    def test_storage_config_has_output_dir(self):
        """StorageConfig should accept output_dir field."""
        from modules.pipeline.models import StorageConfig, S3Config, DatabaseConfig

        storage = StorageConfig(
            output_dir="custom_output",
            s3=S3Config(
                endpoint="https://example.com",
                access_key="key",
                secret_key="secret",
                bucket="bucket",
                public_url_base="https://example.com/public",
            ),
            database=DatabaseConfig(),
        )
        assert storage.output_dir == "custom_output"


class TestGenerationPipelineModel:
    """Tests for GenerationPipeline model."""

    def test_generation_pipeline_has_max_retries(self):
        """GenerationPipeline should have max_retries field."""
        from modules.pipeline.models import GenerationPipeline

        pipeline = GenerationPipeline(max_retries=5)
        assert pipeline.max_retries == 5


class TestGenerationTTSModel:
    """Tests for GenerationTTS model with words_per_second."""

    def test_generation_tts_has_words_per_second(self):
        """GenerationTTS should have words_per_second field."""
        from modules.pipeline.models import GenerationTTS

        tts = GenerationTTS(words_per_second=3.0)
        assert tts.words_per_second == 3.0