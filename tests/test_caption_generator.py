"""Test CaptionGenerator MiniMax LLM fallback."""
import os
from unittest.mock import patch, MagicMock

import pytest
from modules.content.caption_generator import CaptionGenerator


def test_caption_generator_falls_back_to_minimax():
    """CaptionGenerator should try MiniMax LLM when local LLM is unavailable."""
    gen = CaptionGenerator(use_llm=True)
    # Simulate local LLM unavailable (use_llm=False)
    gen.use_llm = False

    mock_minimax = MagicMock()
    # Make MiniMax return None (failed) so template fallback is triggered
    mock_minimax.chat.return_value = "invalid json"

    with patch("modules.llm.minimax.MiniMaxLLMProvider") as MockLLM:
        MockLLM.return_value = mock_minimax

        with patch.dict(os.environ, {"MINIMAX_API_KEY": "fake_key"}):
            with patch.object(gen, "generate_template") as mock_template:
                mock_template.return_value = MagicMock()

                result = gen.generate("Test script", "tiktok")

                # Should have tried MiniMax LLM before falling back to template
                assert MockLLM.called, "MiniMaxLLMProvider was not tried as fallback"
                assert mock_template.called, "Template fallback was not called after MiniMax failed"