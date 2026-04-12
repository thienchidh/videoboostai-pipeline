"""
modules/pipeline/config_loader.py — Configuration loading and merging.

Handles:
- Loading technical base config (YAML/JSON)
- Merging business config
- Merging secrets
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from core.paths import PROJECT_ROOT
from core.video_utils import deep_merge


class MissingConfigError(Exception):
    """Raised when a required configuration key is missing."""
    pass


def require_key(data: Dict, *keys: str) -> Any:
    """Traverse nested dict by keys, raise MissingConfigError if any key is missing or empty."""
    val = data
    for k in keys:
        if not isinstance(val, dict) or k not in val:
            raise MissingConfigError(f"Required config key missing: {'.'.join(keys)}")
        val = val[k]
    if val is None or val == "":
        raise MissingConfigError(f"Required config key is empty: {'.'.join(keys)}")
    return val


@dataclass
class PipelineConfig:
    """Loaded and merged configuration for a pipeline run."""
    # Raw merged config dict
    data: Dict[str, Any]
    # Resolved API keys
    wavespeed_key: str = ""
    wavespeed_base: str = "https://api.wavespeed.ai"
    minimax_key: str = ""
    kieai_key: str = ""
    # Provider preference
    lipsync_provider: str = "wavespeed"
    # S3/MinIO config for media uploads
    s3_endpoint: str = "https://s3.trachanhtv.top"
    s3_access_key: str = "minio-admin"
    s3_secret_key: str = ""
    s3_bucket: str = "videopipeline"
    s3_region: str = "us-east-1"
    s3_public_url_base: str = "https://s3.trachanhtv.top/videopipeline"
    # Derived paths
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    avatars_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "avatars")
    # Run metadata
    timestamp: int = 0
    run_id: str = ""
    run_dir: Path = field(default_factory=lambda: Path("."))
    media_dir: Path = field(default_factory=lambda: Path("."))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """Navigate nested dict with dot-notation keys."""
        val = self.data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default


class ConfigLoader:
    """Loads and merges technical + channel + scenario config files."""

    # Allowlist: only these keys are merged from scenario files
    ALLOWED_SCENARIO_KEYS = {"scenes", "title"}

    @staticmethod
    def load(config_path: str | Path) -> PipelineConfig:
        """Load and merge all config sources.

        Args:
            config_path: Scenario path in format:
                - "{channel_id}" - uses default/latest scenario
                - "{channel_id}/YYYY-MM-DD/{scenario}" - specific scenario
                Examples: "nang_suat_thong_minh", "nang_suat_thong_minh/2026-04-12/3-nguyen-tac"

        Returns:
            PipelineConfig with all merged data and resolved keys
        """
        config_path = Path(config_path)
        parts = config_path.parts if len(config_path.parts) > 1 else [config_path.name]
        channel_id = parts[0]

        # ---- Load technical base config ----
        tech_config_path = PROJECT_ROOT / "configs" / "technical" / "config_technical.yaml"
        if not tech_config_path.exists():
            tech_config_path = PROJECT_ROOT / "configs" / "technical" / "config_technical.json"

        if not tech_config_path.exists():
            raise FileNotFoundError(f"Technical config not found at {tech_config_path}")

        import yaml
        try:
            with open(tech_config_path, encoding="utf-8") as f:
                if tech_config_path.suffix in (".yaml", ".yml"):
                    merged = yaml.safe_load(f)
                else:
                    merged = json.load(f)
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Failed to parse technical config {tech_config_path}: {e}")

        # ---- Load channel config ----
        channel_config_path = PROJECT_ROOT / "configs" / "channels" / channel_id / "config.yaml"
        if channel_config_path.exists():
            try:
                with open(channel_config_path, encoding="utf-8") as f:
                    channel_config = yaml.safe_load(f)
                merged = deep_merge(merged, channel_config)
            except (yaml.YAMLError, json.JSONDecodeError) as e:
                raise RuntimeError(f"Failed to parse channel config {channel_config_path}: {e}")

        # ---- Load scenario with allowlist filter ----
        if len(parts) > 1:
            # scenario path: channel_id/YYYY-MM-DD/scenario_name.yaml
            scenario_date = parts[1]
            scenario_name = parts[2] if len(parts) > 2 else None

            if scenario_name:
                scenario_path = PROJECT_ROOT / "configs" / "channels" / channel_id / "scenarios" / scenario_date / f"{scenario_name}.yaml"
            else:
                # Find first scenario in date folder
                scenario_dir = PROJECT_ROOT / "configs" / "channels" / channel_id / "scenarios" / scenario_date
                yaml_files = list(scenario_dir.glob("*.yaml")) + list(scenario_dir.glob("*.yml"))
                if yaml_files:
                    scenario_path = yaml_files[0]
                else:
                    raise FileNotFoundError(f"No scenario found in {scenario_dir}")
        else:
            # No date provided - find latest scenario
            scenarios_dir = PROJECT_ROOT / "configs" / "channels" / channel_id / "scenarios"
            if scenarios_dir.exists():
                date_dirs = sorted(scenarios_dir.iterdir(), reverse=True)
                for date_dir in date_dirs:
                    yaml_files = list(date_dir.glob("*.yaml")) + list(date_dir.glob("*.yml"))
                    if yaml_files:
                        scenario_path = yaml_files[0]
                        break
                else:
                    raise FileNotFoundError(f"No scenarios found in {scenarios_dir}")
            else:
                raise FileNotFoundError(f"Channel '{channel_id}' has no scenarios directory")

        if scenario_path and scenario_path.exists():
            try:
                with open(scenario_path, encoding="utf-8") as f:
                    raw_scenario = yaml.safe_load(f)
                # Filter to allowlist only - security measure
                filtered_scenario = {k: v for k, v in raw_scenario.items() if k in ConfigLoader.ALLOWED_SCENARIO_KEYS}
                merged = deep_merge(merged, filtered_scenario)
            except (yaml.YAMLError, json.JSONDecodeError) as e:
                raise RuntimeError(f"Failed to parse scenario {scenario_path}: {e}")

        # ---- Load secrets (but do NOT merge into config dict) ----
        secrets = None
        secrets_path = PROJECT_ROOT / "configs" / "business" / "secrets.json"
        if not secrets_path.exists():
            secrets_path = PROJECT_ROOT / "video_config_secrets.json"
        if secrets_path.exists():
            try:
                with open(secrets_path, encoding="utf-8") as f:
                    secrets = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Failed to parse secrets {secrets_path}: {e}")

        # ---- Resolve and validate API keys ----
        wsp_key = require_key(merged, "api", "keys", "wavespeed")
        wsp_base = merged.get("api", {}).get("urls", {}).get("wavespeed", "https://api.wavespeed.ai")
        minimax_key = require_key(merged, "api", "keys", "minimax")
        kieai_key = require_key(merged, "api", "keys", "kie_ai")
        lipsync_provider = merged.get("generation", {}).get("lipsync", {}).get("provider", "wavespeed")

        # ---- Resolve and validate S3 config ----
        s3_cfg = require_key(merged, "storage", "s3")
        s3_endpoint = s3_cfg.get("endpoint", "https://s3.trachanhtv.top")
        s3_access_key = require_key(s3_cfg, "access_key")
        s3_secret_key = require_key(s3_cfg, "secret_key")
        s3_bucket = require_key(s3_cfg, "bucket")
        s3_region = s3_cfg.get("region", "us-east-1")
        s3_public_url_base = s3_cfg.get("public_url_base", "https://s3.trachanhtv.top/videopipeline")

        return PipelineConfig(
            data=merged,
            wavespeed_key=wsp_key,
            wavespeed_base=wsp_base,
            minimax_key=minimax_key,
            kieai_key=kieai_key,
            lipsync_provider=lipsync_provider,
            s3_endpoint=s3_endpoint,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
            s3_public_url_base=s3_public_url_base,
        )
