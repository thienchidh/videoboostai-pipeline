"""
modules/llm — LLM provider package.

Provides swappable LLM backends via PluginRegistry pattern.
"""

import logging
from pathlib import Path
from typing import Optional

from core.plugins import LLMProvider, register_provider, get_provider

logger = logging.getLogger(__name__)

# Register built-in providers
from .minimax import MiniMaxLLMProvider

register_provider("llm", "minimax", MiniMaxLLMProvider)


def _resolve_key_from_config(provider_name: str) -> str:
    """Resolve API key from config_technical.yaml."""
    try:
        import yaml
        cfg_path = Path(__file__).parent.parent.parent / "configs" / "technical" / "config_technical.yaml"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            return cfg.get("api", {}).get("minimax_key", "")
    except Exception:
        pass
    return ""


def get_llm_provider(name: str = "minimax", api_key: str = "",
                     model: str = "MiniMax-M2.7", **kwargs) -> LLMProvider:
    """
    Get an LLM provider instance by name.

    Args:
        name: Provider name (default: "minimax")
        api_key: API key. If empty, resolves from config_technical.yaml
        model: Model name (default: MiniMax-M2.7)
        **kwargs: Additional provider-specific args (max_tokens, timeout, ...)

    Returns:
        LLMProvider instance

    Example:
        llm = get_llm_provider("minimax", model="MiniMax-M2.7")
        response = llm.chat("Hello in Vietnamese")
    """
    # Resolve key from config if not provided
    if not api_key:
        api_key = _resolve_key_from_config(name)

    # Get provider class from registry
    cls = get_provider("llm", name)
    if cls is None:
        logger.warning(f"LLM provider '{name}' not found, defaulting to minimax")
        cls = get_provider("llm", "minimax")
        if cls is None:
            raise ValueError("No LLM provider available")

    return cls(api_key=api_key, model=model, **kwargs)


__all__ = ["LLMProvider", "MiniMaxLLMProvider", "get_llm_provider"]
