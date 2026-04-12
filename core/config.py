"""
core/config.py — ConfigLoader for video pipeline

Handles loading of single config or (business, secrets) tuple,
validation, and safe API key access.
"""

import json
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load and validate pipeline configuration from JSON files."""

    REQUIRED_VIDEO_KEYS: List[str] = ["title", "scenes"]

    def __init__(self, config_path: Union[str, Path, tuple]):
        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load(config_path)

    def _load(self, config_path: Union[str, Path, tuple]) -> None:
        """Load config from single file or (business, secrets) tuple. Supports YAML and JSON."""
        def _load_file(path: Union[str, Path]) -> Dict[str, Any]:
            path = Path(path)
            with open(path, encoding="utf-8") as f:
                if path.suffix in (".yaml", ".yml"):
                    return yaml.safe_load(f) or {}
                return json.load(f)

        if isinstance(config_path, tuple) and len(config_path) == 2:
            business_path, secrets_path = config_path
            business_config = _load_file(business_path)
            secrets_config = _load_file(secrets_path)
            # Merge: secrets override business
            self._config = {**business_config, **secrets_config}
            logger.info(f"📋 Loaded business config: {business_path}")
            logger.info(f"📋 Loaded secrets config: {secrets_path}")
        else:
            self._config = _load_file(config_path)
            logger.info(f"📋 Loaded config: {config_path}")

    def validate(self) -> bool:
        """Check required keys are present. Returns True if valid."""
        missing = []
        for key in self.REQUIRED_VIDEO_KEYS:
            if key not in self._config.get("video", {}):
                missing.append(f"video.{key}")
        if missing:
            logger.warning(f"⚠️ Config missing required keys: {missing}")
            return False
        return True

    def get(self, *keys: str, default: Any = None) -> Any:
        """Safe nested access: config.get('api', 'minimax_key') -> value or default."""
        val = self._config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    @property
    def raw(self) -> Dict[str, Any]:
        """Return the full raw config dict."""
        return self._config

    def get_wavespeed_key(self) -> str:
        """Get WaveSpeed key from config or TOOLS.md fallback."""
        key = self.get("api", "wavespeed_key")
        # Check for placeholder
        if key and key != "REPLACE_WITH_YOUR_WAVESPEED_KEY":
            return key
        # Fallback: scan TOOLS.md
        tools_file = Path.home() / ".openclaw/workspace/TOOLS.md"
        if tools_file.exists():
            content = tools_file.read_text()
            import re
            match = re.search(r'wavespeed.*?([a-f0-9]{64})', content, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    def get_minimax_key(self) -> str:
        """Get MiniMax key from auth-profiles.json or config."""
        auth_file = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
        if auth_file.exists():
            with open(auth_file, encoding="utf-8") as f:
                data = json.load(f)
                for profile in data.get("profiles", {}).values():
                    if profile.get("provider") == "minimax":
                        return profile.get("key", "")
        return self.get("api", "minimax_key", "")

    def get_db_config(self) -> Dict[str, Any]:
        """Get database connection config from config dict or env var fallback."""
        import os
        db = self.get("database", default={})
        return {
            "host": db.get("host", os.environ.get("DB_HOST", "localhost")),
            "port": db.get("port", int(os.environ.get("DB_PORT", "5432"))),
            "name": db.get("name", os.environ.get("DB_NAME", "videopipeline")),
            "user": db.get("user", os.environ.get("DB_USER", "videopipeline")),
            "password": db.get("password", os.environ.get("DB_PASSWORD", "videopipeline123")),
        }

    def get_s3_config(self) -> Dict[str, Any]:
        """Get S3 storage config from config dict or env var fallback."""
        import os
        s3 = self.get("s3", default={})
        return {
            "endpoint": s3.get("endpoint", os.environ.get("S3_ENDPOINT", "")),
            "access_key": s3.get("access_key", os.environ.get("S3_ACCESS_KEY", "")),
            "secret_key": s3.get("secret_key", os.environ.get("S3_SECRET_KEY", "")),
            "bucket": s3.get("bucket", os.environ.get("S3_BUCKET", "videopipeline")),
            "region": s3.get("region", os.environ.get("S3_REGION", "us-east-1")),
            "public_url_base": s3.get("public_url_base", os.environ.get("S3_PUBLIC_URL_BASE", "")),
        }
