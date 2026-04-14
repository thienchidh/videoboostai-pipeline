"""Test CaptionGenerator refactor — PluginRegistry LLM, no ollama."""
import os
from unittest.mock import MagicMock, patch

import pytest
from modules.content.caption_generator import CaptionGenerator


def test_caption_generator_uses_minimax_via_plugin_registry():
    """CaptionGenerator should use LLM provider from PluginRegistry by default."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"headline": "Test Headline", "body": "Test body", "cta": "Test CTA"}'

    with patch("modules.content.caption_generator.get_provider") as mock_get:
        mock_provider_cls = MagicMock(return_value=mock_llm)
        mock_get.return_value = mock_provider_cls

        with patch.dict(os.environ, {"MINIMAX_API_KEY": "fake_key"}):
            gen = CaptionGenerator()  # no args — should default to PluginRegistry LLM
            result = gen.generate("Test script video", "tiktok")

        # Verify get_provider was called for 'llm' category with 'minimax'
        mock_get.assert_called_with("llm", "minimax")
        assert mock_llm.chat.called
        assert result is not None
        assert result.headline == "Test Headline"


def test_caption_generator_accepts_custom_llm_provider():
    """CaptionGenerator should accept custom LLM provider via constructor."""
    custom_provider = MagicMock()
    custom_provider.chat.return_value = '{"headline": "Custom", "body": "Custom body", "cta": "Custom CTA"}'

    gen = CaptionGenerator(llm_provider=custom_provider)
    result = gen.generate("Test script", "facebook")

    assert result.headline == "Custom"
    assert custom_provider.chat.called


def test_caption_generator_no_ollama_code():
    """CaptionGenerator should have no ollama imports or references."""
    from pathlib import Path

    caption_file = Path("modules/content/caption_generator.py")
    content = caption_file.read_text(encoding="utf-8")

    # Check for ollama/disallowed names
    ollama_names = ["ollama", "subprocess", "_check_ollama", "generate_llm", "use_llm"]
    for name in ollama_names:
        assert name not in content, f"Found '{name}' in CaptionGenerator — ollama code must be removed"

    assert "curl" not in content, "curl calls found — ollama code not removed"
    assert "llama3.2" not in content, "llama model reference found — ollama code not removed"