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
    kieai_webhook_key: str = ""
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
    """Loads and merges technical + business + secrets config files."""

    @staticmethod
    def load(config_path: str | Path) -> PipelineConfig:
        """Load and merge all config sources.

        Args:
            config_path: Path to business config file, or just technical config name

        Returns:
            PipelineConfig with all merged data and resolved keys
        """
        config_path = Path(config_path)

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

        # ---- Load and merge business config ----
        if config_path.name not in ("config_technical.json", "config_technical.yaml"):
            # Try as-is first
            if not config_path.exists():
                # Try configs/business/{name}.yaml
                biz_path = PROJECT_ROOT / "configs" / "business" / f"{config_path.name}.yaml"
                if biz_path.exists():
                    config_path = biz_path
                else:
                    # Try configs/business/{name}.json
                    biz_path_json = PROJECT_ROOT / "configs" / "business" / f"{config_path.name}.json"
                    if biz_path_json.exists():
                        config_path = biz_path_json
                    else:
                        # Try configs/business/{name} directly (e.g. video_scenario.yaml.example)
                        biz_path_direct = PROJECT_ROOT / "configs" / "business" / config_path.name
                        if biz_path_direct.exists():
                            config_path = biz_path_direct

            if config_path.exists():
                try:
                    with open(config_path, encoding="utf-8") as f:
                        # Business configs in configs/business/ are always YAML
                        if "configs" in str(config_path.resolve()):
                            biz_config = yaml.safe_load(f)
                        elif str(config_path).endswith((".yaml", ".yml")):
                            biz_config = yaml.safe_load(f)
                        else:
                            biz_config = json.load(f)
                    merged = deep_merge(merged, biz_config)
                except (yaml.YAMLError, json.JSONDecodeError) as e:
                    raise RuntimeError(f"Failed to parse business config {config_path}: {e}")

        # ---- Load secrets ----
        secrets_path = PROJECT_ROOT / "configs" / "business" / "secrets.json"
        if not secrets_path.exists():
            secrets_path = PROJECT_ROOT / "video_config_secrets.json"
        if secrets_path.exists():
            try:
                with open(secrets_path, encoding="utf-8") as f:
                    secrets_data = json.load(f)
                merged = deep_merge(merged, secrets_data)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Failed to parse secrets {secrets_path}: {e}")

        # ---- Resolve API keys ----
        wsp_key = merged.get("api", {}).get("wavespeed_key", "")
        wsp_base = merged.get("api_urls", {}).get("wavespeed", "https://api.wavespeed.ai")
        minimax_key = merged.get("api", {}).get("minimax_key", "")
        kieai_key = merged.get("api", {}).get("kie_ai_key", "")
        kieai_webhook_key = merged.get("api", {}).get("kie_ai_webhook_key", "")
        lipsync_provider = merged.get("lipsync", {}).get("provider", "wavespeed")

        # ---- Resolve S3 config ----
        s3_cfg = merged.get("s3", {})
        s3_endpoint = s3_cfg.get("endpoint", "https://s3.trachanhtv.top")
        s3_access_key = s3_cfg.get("access_key", "minio-admin")
        s3_secret_key = s3_cfg.get("secret_key", "")
        s3_bucket = s3_cfg.get("bucket", "videopipeline")
        s3_region = s3_cfg.get("region", "us-east-1")
        s3_public_url_base = s3_cfg.get("public_url_base", "https://s3.trachanhtv.top/videopipeline")

        return PipelineConfig(
            data=merged,
            wavespeed_key=wsp_key,
            wavespeed_base=wsp_base,
            minimax_key=minimax_key,
            kieai_key=kieai_key,
            kieai_webhook_key=kieai_webhook_key,
            lipsync_provider=lipsync_provider,
            s3_endpoint=s3_endpoint,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
            s3_public_url_base=s3_public_url_base,
        )
