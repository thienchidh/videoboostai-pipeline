"""
modules/llm — LLM provider package.

Provides swappable LLM backends via PluginRegistry pattern.
"""

import logging
from typing import Optional

from core.plugins import LLMProvider, register_provider, get_provider

logger = logging.getLogger(__name__)

# Register built-in providers
from .minimax import MiniMaxLLMProvider

register_provider("llm", "minimax", MiniMaxLLMProvider)


def get_llm_provider(name: str = "minimax", api_key: str = "",
                     model: str = "MiniMax-M2.7", **kwargs) -> LLMProvider:
    """
    Get an LLM provider instance by name.

    Args:
        name: Provider name (default: "minimax")
        api_key: API key. Caller should resolve from PipelineContext.
        model: Model name (default: MiniMax-M2.7)
        **kwargs: Additional provider-specific args (max_tokens, timeout, api_url, ...)

    Returns:
        LLMProvider instance

    Example:
        llm = get_llm_provider("minimax", api_key="your-key", model="MiniMax-M2.7")
        response = llm.chat("Hello in Vietnamese")
    """
    # api_key must be provided by caller (resolved from PipelineContext)
    if not api_key:
        raise ValueError("api_key is required for LLM provider. Use PipelineContext to resolve.")

    # Get provider class from registry
    cls = get_provider("llm", name)
    if cls is None:
        logger.warning(f"LLM provider '{name}' not found, defaulting to minimax")
        cls = get_provider("llm", "minimax")
        if cls is None:
            raise ValueError("No LLM provider available")

    return cls(api_key=api_key, model=model, **kwargs)


__all__ = ["LLMProvider", "MiniMaxLLMProvider", "get_llm_provider"]
