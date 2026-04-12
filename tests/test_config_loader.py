"""
tests/test_config_loader.py — Tests for ConfigLoader
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestPipelineConfig:
    """Test PipelineConfig dataclass."""

    def test_pipeline_config_get_nested(self):
        """Test PipelineConfig.get_nested() method for nested access."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"api": {"minimax_key": "test_key"}, "models": {"tts": "edge"}},
            minimax_key="test_key",
        )

        assert config.get_nested("api", "minimax_key") == "test_key"
        assert config.get_nested("models", "tts") == "edge"
        assert config.get_nested("nonexistent", "key", default="default") == "default"

    def test_pipeline_config_get_top_level(self):
        """Test PipelineConfig.get() for top-level keys."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"title": "Test Video", "models": {"tts": "edge"}},
        )

        assert config.get("title") == "Test Video"
        assert config.get("models") == {"tts": "edge"}
        assert config.get("nonexistent", default="fallback") == "fallback"


class TestConfigLoader:
    """Test ConfigLoader class."""

    def test_load_technical_config_uses_yaml_values(self, tmp_path):
        """Test that ConfigLoader uses the yaml values directly."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create minimal config structure
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)

        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  wavespeed_key: test_wavespeed_key\n"
            "  minimax_key: test_minimax_key\n"
        )

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("config_technical")

        assert config.wavespeed_key == "test_wavespeed_key"
        assert config.minimax_key == "test_minimax_key"

    def test_load_with_business_config_merge(self, tmp_path):
        """Test that business config merges with technical config."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  wavespeed_key: tech_key\n"
            "  minimax_key: tech_minimax\n"
        )

        # Create business config
        biz_dir = tmp_path / "configs" / "business"
        biz_dir.mkdir(parents=True)
        biz_file = biz_dir / "test_scenario.yaml"
        biz_file.write_text("title: Test Video\nscenes:\n  - id: 1\n    script: test\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("test_scenario")

        assert config.wavespeed_key == "tech_key"
        assert config.get("title") == "Test Video"

    def test_load_with_secrets_override(self, tmp_path):
        """Test that secrets.json overrides config values."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text("api:\n  wavespeed_key: tech_key\n")

        # Create secrets
        biz_dir = tmp_path / "configs" / "business"
        biz_dir.mkdir(parents=True)
        secrets_file = biz_dir / "secrets.json"
        secrets_file.write_text('{"api": {"wavespeed_key": "secret_key"}}')

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("config_technical")

        assert config.wavespeed_key == "secret_key"

    def test_lipsync_provider_from_config(self, tmp_path):
        """Test that lipsync provider is read from config."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "lipsync:\n"
            "  provider: kieai\n"
            "api:\n"
            "  kie_ai_key: test_key\n"
        )

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("config_technical")

        assert config.lipsync_provider == "kieai"

    def test_api_urls_loaded(self, tmp_path):
        """Test that api_urls are available in config data."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  urls:\n"
            "    minimax_tts: https://custom.tts.api\n"
            "    wavespeed: https://custom.wavespeed.api\n"
        )

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("config_technical")

        assert config.get_nested("api", "urls", "minimax_tts") == "https://custom.tts.api"
        assert config.get_nested("api", "urls", "wavespeed") == "https://custom.wavespeed.api"


class TestConfigLoaderErrors:
    """Test ConfigLoader error handling."""

    def test_load_missing_technical_config_raises(self, tmp_path):
        """Test that missing technical config raises FileNotFoundError."""
        from modules.pipeline.config_loader import ConfigLoader

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            with pytest.raises(FileNotFoundError):
                ConfigLoader.load("config_technical")

    def test_load_invalid_yaml_raises(self, tmp_path):
        """Test that invalid YAML raises RuntimeError."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text("invalid: yaml: content: [\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            with pytest.raises(RuntimeError):
                ConfigLoader.load("config_technical")
