"""Test CaptionGenerator and ABCaptionGenerator refactor — PluginRegistry LLM, no ollama."""
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
    """CaptionGenerator and ABCaptionGenerator should have no ollama imports or references."""
    from pathlib import Path

    caption_file = Path("modules/content/caption_generator.py")
    content_caption = caption_file.read_text(encoding="utf-8")

    ab_caption_file = Path("modules/content/ab_caption_generator.py")
    content_ab_caption = ab_caption_file.read_text(encoding="utf-8")

    # Check for ollama/disallowed names
    ollama_names = ["ollama", "subprocess", "_check_ollama", "generate_llm", "use_llm", "curl", "ollama_host", "llama3.2"]
    for name in ollama_names:
        assert name not in content_caption, f"Found '{name}' in CaptionGenerator — ollama code must be removed"
        assert name not in content_ab_caption, f"Found '{name}' in ABCaptionGenerator — ollama code must be removed"


def test_ab_caption_generator_template_generation():
    """ABCaptionGenerator should generate valid captions via template fallback."""
    from modules.content.ab_caption_generator import ABCaptionGenerator

    gen = ABCaptionGenerator()
    result = gen.generate_ab_captions(
        "Hải sản là nguồn dinh dưỡng tuyệt vời cho sức khỏe. "
        "Ăn hải sản đúng cách sẽ giúp bạn sống khỏe hơn mỗi ngày.",
        "tiktok"
    )

    assert result.variant_a is not None
    assert result.variant_b is not None
    assert result.variant_a.headline
    assert result.variant_b.headline
    assert "🔥" in result.variant_a.full_caption
    assert "❓" in result.variant_b.full_caption
    assert len(result.variant_a.hashtags) <= 5
    assert len(result.variant_b.hashtags) <= 5