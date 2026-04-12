"""
tests/test_pipeline_runner.py — Tests for VideoPipelineRunner
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, Mock, call


# Mock db module before importing pipeline_runner
mock_db = MagicMock()
sys.modules['db'] = mock_db


class TestVideoPipelineRunnerInit:
    """Test VideoPipelineRunner initialization."""

    def test_runner_stores_config(self, tmp_path):
        """Test that runner stores config correctly."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"tts": "edge", "image": "minimax"}},
            minimax_key="test_minimax",
            wavespeed_key="test_wavespeed",
            output_dir=tmp_path / "output",
            run_id="test_run",
        )

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

        assert runner.config is config
        assert runner.config.minimax_key == "test_minimax"
        assert runner.config.wavespeed_key == "test_wavespeed"

    def test_runner_creates_directories(self, tmp_path):
        """Test that runner creates necessary directories."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"tts": "edge", "image": "minimax"}},
            output_dir=tmp_path / "output",
            run_id="test_run",
        )

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

        assert (tmp_path / "output").exists()


class TestProviderBuilders:
    """Test provider building methods."""

    def test_build_tts_provider_minimax(self, tmp_path):
        """Test building MiniMax TTS provider passes correct api_key."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"tts": "minimax"}},
            minimax_key="my_minimax_key",
            wavespeed_key="my_wavespeed_key",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        mock_tts_cls = MagicMock()
        mock_img_cls = MagicMock()
        mock_lip_cls = MagicMock()

        def mock_get_provider(category, name):
            if category == "tts":
                return mock_tts_cls
            elif category == "image":
                return mock_img_cls
            elif category == "lipsync":
                return mock_lip_cls
            return None

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

        # TTS should be called with minimax_key
        mock_tts_cls.assert_called_once_with(api_key="my_minimax_key")

    def test_build_tts_provider_edge(self, tmp_path):
        """Test building Edge TTS provider uses upload_func."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"tts": "edge"}},
            minimax_key="my_minimax_key",
            wavespeed_key="my_wavespeed_key",
            wavespeed_base="https://api.wavespeed.ai",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        mock_tts_cls = MagicMock()
        mock_img_cls = MagicMock()
        mock_lip_cls = MagicMock()

        def mock_get_provider(category, name):
            if category == "tts":
                return mock_tts_cls
            elif category == "image":
                return mock_img_cls
            elif category == "lipsync":
                return mock_lip_cls
            return None

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

        # Edge TTS should be called with upload_func
        tts_call = mock_tts_cls.call_args
        assert 'upload_func' in tts_call.kwargs or len(tts_call.args) > 0

    def test_build_image_provider_minimax(self, tmp_path):
        """Test building MiniMax image provider passes wavespeed_key."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"image": "minimax"}},
            wavespeed_key="my_wavespeed_key",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        mock_tts_cls = MagicMock()
        mock_img_cls = MagicMock()
        mock_lip_cls = MagicMock()

        def mock_get_provider(category, name):
            if category == "tts":
                return mock_tts_cls
            elif category == "image":
                return mock_img_cls
            elif category == "lipsync":
                return mock_lip_cls
            return None

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

        # Image should be called with wavespeed_key
        mock_img_cls.assert_called_once_with(api_key="my_wavespeed_key")

    def test_build_lipsync_provider_kieai(self, tmp_path):
        """Test building KieAI lipsync provider passes correct keys."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={},
            lipsync_provider="kieai",
            kieai_key="test_kieai",
            kieai_webhook_key="test_webhook",
            wavespeed_key="my_wavespeed",
            wavespeed_base="https://api.wavespeed.ai",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        mock_tts_cls = MagicMock()
        mock_img_cls = MagicMock()
        mock_lip_cls = MagicMock()

        def mock_get_provider(category, name):
            if category == "tts":
                return mock_tts_cls
            elif category == "image":
                return mock_img_cls
            elif category == "lipsync":
                return mock_lip_cls
            return None

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

        # Lipsync KieAI should be called with kieai keys
        mock_lip_cls.assert_called_once()
        lip_call = mock_lip_cls.call_args
        assert lip_call.kwargs['api_key'] == "test_kieai"
        assert lip_call.kwargs['webhook_key'] == "test_webhook"


class TestDRYRunModes:
    """Test DRY_RUN mode behavior."""

    def test_dry_run_tts_returns_mock(self, tmp_path):
        """Test that dry_run returns mock TTS."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"tts": "edge"}},
            minimax_key="test_key",
            wavespeed_key="test_wavespeed",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        mock_tts_cls = MagicMock()
        mock_img_cls = MagicMock()
        mock_lip_cls = MagicMock()

        def mock_get_provider(category, name):
            if category == "tts":
                return mock_tts_cls
            elif category == "image":
                return mock_img_cls
            elif category == "lipsync":
                return mock_lip_cls
            return None

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'), \
             patch('core.video_utils.mock_generate_tts') as mock_tts:

            mock_tts.return_value = "/tmp/dry_tts.mp3"

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

            result = runner.tts_generate("test text", "female_voice", 1.0, "/tmp/output.mp3")

            mock_tts.assert_called_once()
            assert result[0] == "/tmp/dry_tts.mp3"

    def test_dry_run_images_returns_mock(self, tmp_path):
        """Test that dry_run returns mock image."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"image": "minimax"}},
            wavespeed_key="test_key",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        mock_tts_cls = MagicMock()
        mock_img_cls = MagicMock()
        mock_lip_cls = MagicMock()

        def mock_get_provider(category, name):
            if category == "tts":
                return mock_tts_cls
            elif category == "image":
                return mock_img_cls
            elif category == "lipsync":
                return mock_lip_cls
            return None

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'), \
             patch('core.video_utils.mock_generate_image') as mock_img:

            mock_img.return_value = "/tmp/dry_image.png"

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            runner = VideoPipelineRunner(config, dry_run=True)

            result = runner.image_generate("test prompt", "/tmp/output.png")

            mock_img.assert_called_once()
            assert result == "/tmp/dry_image.png"


class TestProviderUnknownRaises:
    """Test that unknown providers raise ValueError."""

    def test_unknown_tts_provider_raises(self, tmp_path):
        """Test that unknown TTS provider raises ValueError."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"models": {"tts": "unknown_tts"}},
            minimax_key="test_minimax",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        def mock_get_provider(category, name):
            if category == "tts":
                return None  # Unknown provider
            return MagicMock()

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            with pytest.raises(ValueError, match="Unknown TTS provider"):
                VideoPipelineRunner(config, dry_run=True)

    def test_unknown_lipsync_provider_raises(self, tmp_path):
        """Test that unknown lipsync provider raises ValueError."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={},
            lipsync_provider="unknown_lipsync",
            wavespeed_key="test_wavespeed",
            wavespeed_base="https://api.wavespeed.ai",
            output_dir=tmp_path / "output",
            run_id="test",
        )

        def mock_get_provider(category, name):
            if category == "lipsync":
                return None  # Unknown provider
            return MagicMock()

        with patch('modules.pipeline.pipeline_runner.SingleCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.MultiCharSceneProcessor'), \
             patch('modules.pipeline.pipeline_runner.get_provider', side_effect=mock_get_provider), \
             patch('modules.pipeline.pipeline_runner.upload_file'):

            from modules.pipeline.pipeline_runner import VideoPipelineRunner
            with pytest.raises(ValueError, match="Unknown lipsync provider"):
                VideoPipelineRunner(config, dry_run=True)
