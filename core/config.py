"""
core/config.py — ConfigLoader for video pipeline

Handles loading of single config or (business, secrets) tuple,
validation, and safe API key access.
"""

import json
import logging
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
        """Load config from single file or (business, secrets) tuple."""
        if isinstance(config_path, tuple) and len(config_path) == 2:
            business_path, secrets_path = config_path
            with open(business_path, encoding="utf-8") as f:
                business_config = json.load(f)
            with open(secrets_path, encoding="utf-8") as f:
                secrets_config = json.load(f)
            # Merge: secrets override business
            self._config = {**business_config, **secrets_config}
            logger.info(f"📋 Loaded business config: {business_path}")
            logger.info(f"📋 Loaded secrets config: {secrets_path}")
        else:
            with open(config_path, encoding="utf-8") as f:
                self._config = json.load(f)
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
