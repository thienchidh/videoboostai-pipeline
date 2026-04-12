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
        """Test that ConfigLoader uses the yaml values when no auth file exists."""
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

        # Patch get_config_path in config_loader's namespace
        fake_auth = tmp_path / "nonexistent_auth.json"

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=fake_auth):
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

        fake_auth = tmp_path / "nonexistent_auth.json"
        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=fake_auth):
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

        fake_auth = tmp_path / "nonexistent_auth.json"
        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=fake_auth):
            config = ConfigLoader.load("config_technical")

        assert config.wavespeed_key == "secret_key"

    def test_wavespeed_key_placeholder_triggers_fallback(self, tmp_path):
        """Test that REPLACE_WITH_YOUR_WAVESPEED_KEY triggers TOOLS.md fallback."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text("api:\n  wavespeed_key: REPLACE_WITH_YOUR_WAVESPEED_KEY\n")

        # Create TOOLS.md with fallback key at the path get_config_path would return
        tools_dir = tmp_path / ".openclaw" / "workspace"
        tools_dir.mkdir(parents=True)
        tools_file = tools_dir / "TOOLS.md"
        tools_file.write_text(
            "wavespeed_api_key = abc123def456789012345678901234567890123456789012345678901234abcd"
        )

        # When get_config_path is called with "workspace/TOOLS.md", return our test file
        def fake_get_config(rel):
            if rel == "workspace/TOOLS.md":
                return tools_file
            return tmp_path / ".openclaw" / rel

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', side_effect=fake_get_config):
            config = ConfigLoader.load("config_technical")

        assert config.wavespeed_key == "abc123def456789012345678901234567890123456789012345678901234abcd"

    def test_minimax_key_from_auth_profiles(self, tmp_path):
        """Test that minimax_key is resolved from auth-profiles.json first."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text("api:\n  minimax_key: yaml_key\n")

        # Create auth-profiles.json at the path get_config_path would return
        auth_dir = tmp_path / ".openclaw" / "agents" / "main" / "agent"
        auth_dir.mkdir(parents=True)
        auth_file = auth_dir / "auth-profiles.json"
        auth_file.write_text(json.dumps({
            "profiles": {
                "work": {"provider": "minimax", "key": "auth_key_from_profile"}
            }
        }))

        def fake_get_config(rel):
            if "auth-profiles.json" in rel:
                return auth_file
            return tmp_path / ".openclaw" / rel

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', side_effect=fake_get_config):
            config = ConfigLoader.load("config_technical")

        assert config.minimax_key == "auth_key_from_profile"

    def test_lipsync_provider_kieai_fallback_to_wavespeed(self, tmp_path):
        """Test that lipsync provider falls back to wavespeed if kieai key missing."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "lipsync:\n"
            "  provider: kieai\n"
            "api:\n"
            "  kie_ai_key: \"\"\n"
        )

        fake_auth = tmp_path / "nonexistent_auth.json"
        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=fake_auth):
            config = ConfigLoader.load("config_technical")

        assert config.lipsync_provider == "wavespeed"

    def test_api_urls_loaded(self, tmp_path):
        """Test that api_urls are available in config data."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text(
            "api_urls:\n"
            "  minimax_tts: https://custom.tts.api\n"
            "  wavespeed: https://custom.wavespeed.api\n"
        )

        fake_auth = tmp_path / "nonexistent_auth.json"
        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=fake_auth):
            config = ConfigLoader.load("config_technical")

        assert config.get_nested("api_urls", "minimax_tts") == "https://custom.tts.api"
        assert config.get_nested("api_urls", "wavespeed") == "https://custom.wavespeed.api"


class TestConfigLoaderErrors:
    """Test ConfigLoader error handling."""

    def test_load_missing_technical_config_raises(self, tmp_path):
        """Test that missing technical config raises FileNotFoundError."""
        from modules.pipeline.config_loader import ConfigLoader

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=tmp_path / "nonexistent"):
            with pytest.raises(FileNotFoundError):
                ConfigLoader.load("config_technical")

    def test_load_invalid_yaml_raises(self, tmp_path):
        """Test that invalid YAML raises RuntimeError."""
        from modules.pipeline.config_loader import ConfigLoader

        tech_dir = tmp_path / "configs" / "technical"
        tech_dir.mkdir(parents=True)
        tech_file = tech_dir / "config_technical.yaml"
        tech_file.write_text("invalid: yaml: content: [\n")

        with patch('modules.pipeline.config_loader.PROJECT_ROOT', tmp_path), \
             patch('modules.pipeline.config_loader.get_config_path', return_value=tmp_path / "nonexistent"):
            with pytest.raises(RuntimeError):
                ConfigLoader.load("config_technical")
