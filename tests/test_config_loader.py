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
            data={"api": {"keys": {"minimax": "test_key"}}, "generation": {"models": {"tts": "edge"}}},
        )

        assert config.get_nested("api", "keys", "minimax") == "test_key"
        assert config.get_nested("generation", "models", "tts") == "edge"
        assert config.get_nested("nonexistent", "key", default="default") == "default"

    def test_pipeline_config_get_top_level(self):
        """Test PipelineConfig.get() for top-level keys."""
        from modules.pipeline.config_loader import PipelineConfig

        config = PipelineConfig(
            data={"title": "Test Video", "generation": {"models": {"tts": "edge"}}},
        )

        assert config.get("title") == "Test Video"
        assert config.get("generation") == {"models": {"tts": "edge"}}
        assert config.get("nonexistent", default="fallback") == "fallback"


class TestConfigLoader:
    """Test ConfigLoader class with channel-based structure."""

    def test_load_technical_config_uses_yaml_values(self, tmp_path):
        """Test that ConfigLoader uses the yaml values from technical config."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create channel structure
        channel_dir = tmp_path / "configs" / "channels" / "test_channel"
        scenarios_dir = channel_dir / "scenarios" / "2026-04-13"
        scenarios_dir.mkdir(parents=True)

        # Technical config (matches new structure: api.keys.wavespeed, storage.s3)
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  keys:\n"
            "    wavespeed: test_wavespeed_key\n"
            "    minimax: test_minimax_key\n"
            "    kie_ai: test_kieai_key\n"
            "  urls:\n"
            "    wavespeed: https://api.wavespeed.ai\n"
            "storage:\n"
            "  s3:\n"
            "    endpoint: https://s3.test.com\n"
            "    access_key: test_key\n"
            "    secret_key: test_secret\n"
            "    bucket: test_bucket\n"
        )

        # Channel config
        channel_file = channel_dir / "config.yaml"
        channel_file.write_text("channel:\n  id: test_channel\n")

        # Scenario
        scenario_file = scenarios_dir / "test_scenario.yaml"
        scenario_file.write_text(
            "title: Test Scenario\n"
            "scenes:\n"
            "  - id: 1\n"
            "    script: test script\n"
        )

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("test_channel/2026-04-13/test_scenario")

        assert config.wavespeed_key == "test_wavespeed_key"
        assert config.minimax_key == "test_minimax_key"

    def test_load_with_channel_config_merge(self, tmp_path):
        """Test that channel config merges with technical config."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create channel structure
        channel_dir = tmp_path / "configs" / "channels" / "test_channel"
        scenarios_dir = channel_dir / "scenarios" / "2026-04-13"
        scenarios_dir.mkdir(parents=True)

        # Technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  keys:\n"
            "    wavespeed: tech_key\n"
            "    minimax: tech_minimax\n"
            "    kie_ai: tech_kieai\n"
            "storage:\n"
            "  s3:\n"
            "    endpoint: https://s3.test.com\n"
            "    access_key: test_key\n"
            "    secret_key: test_secret\n"
            "    bucket: test_bucket\n"
            "generation:\n"
            "  lipsync:\n"
            "    provider: kieai\n"
        )

        # Channel config with override
        channel_file = channel_dir / "config.yaml"
        channel_file.write_text(
            "generation:\n"
            "  lipsync:\n"
            "    provider: wavespeed\n"
        )

        # Scenario
        scenario_file = scenarios_dir / "test_scenario.yaml"
        scenario_file.write_text("title: Test Video\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("test_channel/2026-04-13/test_scenario")

        assert config.wavespeed_key == "tech_key"
        assert config.get("title") == "Test Video"
        assert config.lipsync_provider == "wavespeed"

    def test_lipsync_provider_from_config(self, tmp_path):
        """Test that lipsync provider is read from config."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create channel structure
        channel_dir = tmp_path / "configs" / "channels" / "test_channel"
        scenarios_dir = channel_dir / "scenarios" / "2026-04-13"
        scenarios_dir.mkdir(parents=True)

        # Technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  keys:\n"
            "    wavespeed: test_wavespeed\n"
            "    minimax: test_minimax\n"
            "    kie_ai: test_key\n"
            "storage:\n"
            "  s3:\n"
            "    endpoint: https://s3.test.com\n"
            "    access_key: test_key\n"
            "    secret_key: test_secret\n"
            "    bucket: test_bucket\n"
            "generation:\n"
            "  lipsync:\n"
            "    provider: kieai\n"
        )

        # Channel config
        channel_file = channel_dir / "config.yaml"
        channel_file.write_text("channel:\n  id: test_channel\n")

        # Scenario
        scenario_file = scenarios_dir / "test_scenario.yaml"
        scenario_file.write_text("title: Test\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("test_channel/2026-04-13/test_scenario")

        assert config.lipsync_provider == "kieai"

    def test_api_urls_loaded(self, tmp_path):
        """Test that api_urls are available in config data."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create channel structure
        channel_dir = tmp_path / "configs" / "channels" / "test_channel"
        scenarios_dir = channel_dir / "scenarios" / "2026-04-13"
        scenarios_dir.mkdir(parents=True)

        # Technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  keys:\n"
            "    wavespeed: test_key\n"
            "    minimax: test_minimax\n"
            "    kie_ai: test_kieai\n"
            "  urls:\n"
            "    minimax_tts: https://custom.tts.api\n"
            "    wavespeed: https://custom.wavespeed.api\n"
            "storage:\n"
            "  s3:\n"
            "    endpoint: https://s3.test.com\n"
            "    access_key: test_key\n"
            "    secret_key: test_secret\n"
            "    bucket: test_bucket\n"
        )

        # Channel config
        channel_file = channel_dir / "config.yaml"
        channel_file.write_text("channel:\n  id: test_channel\n")

        # Scenario
        scenario_file = scenarios_dir / "test_scenario.yaml"
        scenario_file.write_text("title: Test\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("test_channel/2026-04-13/test_scenario")

        assert config.get_nested("api", "urls", "minimax_tts") == "https://custom.tts.api"
        assert config.get_nested("api", "urls", "wavespeed") == "https://custom.wavespeed.api"

    def test_load_finds_latest_scenario(self, tmp_path):
        """Test that loading channel_id without date finds latest scenario."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create channel structure
        channel_dir = tmp_path / "configs" / "channels" / "test_channel"
        scenarios_dir = channel_dir / "scenarios"
        scenarios_dir.mkdir(parents=True)

        # Technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  keys:\n"
            "    wavespeed: test_key\n"
            "    minimax: test_minimax\n"
            "    kie_ai: test_kieai\n"
            "storage:\n"
            "  s3:\n"
            "    endpoint: https://s3.test.com\n"
            "    access_key: test_key\n"
            "    secret_key: test_secret\n"
            "    bucket: test_bucket\n"
        )

        # Channel config
        channel_file = channel_dir / "config.yaml"
        channel_file.write_text("channel:\n  id: test_channel\n")

        # Earlier scenario
        early_dir = scenarios_dir / "2026-04-10"
        early_dir.mkdir(parents=True)
        early_file = early_dir / "old_scenario.yaml"
        early_file.write_text("title: Old\n")

        # Latest scenario
        latest_dir = scenarios_dir / "2026-04-13"
        latest_dir.mkdir(parents=True)
        latest_file = latest_dir / "new_scenario.yaml"
        latest_file.write_text("title: Latest Title\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            config = ConfigLoader.load("test_channel")

        assert config.get("title") == "Latest Title"


class TestConfigLoaderErrors:
    """Test ConfigLoader error handling."""

    def test_load_missing_technical_config_raises(self, tmp_path):
        """Test that missing technical config raises FileNotFoundError."""
        from modules.pipeline.config_loader import ConfigLoader

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            with pytest.raises(FileNotFoundError):
                ConfigLoader.load("any_channel")

    def test_load_invalid_yaml_raises(self, tmp_path):
        """Test that invalid YAML raises RuntimeError."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create channel structure
        channel_dir = tmp_path / "configs" / "channels" / "test_channel"
        scenarios_dir = channel_dir / "scenarios" / "2026-04-13"
        scenarios_dir.mkdir(parents=True)

        # Technical config with invalid YAML
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text("invalid: yaml: content: [\n")

        # Channel config
        channel_file = channel_dir / "config.yaml"
        channel_file.write_text("channel:\n  id: test\n")

        # Scenario
        scenario_file = scenarios_dir / "test.yaml"
        scenario_file.write_text("title: Test\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            with pytest.raises(RuntimeError):
                ConfigLoader.load("test_channel/2026-04-13/test")

    def test_load_nonexistent_channel_raises(self, tmp_path):
        """Test that nonexistent channel raises FileNotFoundError."""
        from modules.pipeline.config_loader import ConfigLoader

        # Create only technical config
        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api:\n"
            "  keys:\n"
            "    wavespeed: test\n"
            "    minimax: test\n"
            "    kie_ai: test\n"
            "storage:\n"
            "  s3:\n"
            "    endpoint: https://s3.test.com\n"
            "    access_key: test_key\n"
            "    secret_key: test_secret\n"
            "    bucket: test_bucket\n"
        )

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path):
            with pytest.raises(FileNotFoundError):
                ConfigLoader.load("nonexistent_channel")
