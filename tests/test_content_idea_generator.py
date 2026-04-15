"""Tests for ContentIdeaGenerator."""
import pytest
from unittest.mock import MagicMock, patch


def test_estimate_tts_duration():
    """Word count / wps gives estimated duration."""
    from modules.content.content_idea_generator import ContentIdeaGenerator
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["test"],
        channel_config={
            "channel_id": "test_channel",
            "name": "Test",
            "characters": [{"name": "Mentor", "voice_id": "x"}],
            "tts": {"max_duration": 15.0, "min_duration": 5.0},
            "watermark": {"text": "Test"},
            "style": "3D render",
            "research": {"niche_keywords": ["test"]},
        },
    )
    # 30 words at 2.5 wps = 12 seconds
    estimated = gen._estimate_tts_duration(
        "đây là một câu dài để test thử nghiệm cho nhanh và cũng giúp kiểm tra chức năng "
        "ước tính thời lượng văn bản tiếng việt một cách chính xác",
        wps=2.5,
    )
    assert 11.5 < estimated < 12.5, f"expected ~12s, got {estimated}"


class TestContentIdeaGenerator:
    def test_validate_scene_duration_passes(self):
        """Scene within min/max bounds returns True."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import TTSConfig
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["test"],
            channel_config={
                "name": "Test",
                "channel_id": "test",
                "characters": [{"name": "Mentor", "voice_id": "x"}],
                "watermark": {"text": "@Test", "enable": True, "font_size": 30, "opacity": 0.15, "motion": "bounce", "bounce_speed": 80, "bounce_padding": 20, "velocity_x": 1.2, "velocity_y": 0.8, "margin": 8},
                "style": "3D render",
                "research": {"niche_keywords": ["test"], "content_angle": "tips", "target_platform": "both", "research_interval_hours": 24, "pending_pool_size": 5, "threshold": 3},
                "tts": {"max_duration": 15.0, "min_duration": 5.0},
            },
        )
        tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
        # 30 words at 2.5 wps = 12s — within 5-15s
        text = "đây là một câu dài để test thử nghiệm cho nhanh đấy nhé"
        result = gen._validate_scene_duration(text, tts_cfg, wps=2.5)
        assert result is True

    def test_validate_scene_duration_fails_too_long(self):
        """Scene exceeding max_duration returns False."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import TTSConfig
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["test"],
            channel_config={
                "name": "Test",
                "channel_id": "test",
                "characters": [{"name": "Mentor", "voice_id": "x"}],
                "watermark": {"text": "@Test", "enable": True, "font_size": 30, "opacity": 0.15, "motion": "bounce", "bounce_speed": 80, "bounce_padding": 20, "velocity_x": 1.2, "velocity_y": 0.8, "margin": 8},
                "style": "3D render",
                "research": {"niche_keywords": ["test"], "content_angle": "tips", "target_platform": "both", "research_interval_hours": 24, "pending_pool_size": 5, "threshold": 3},
                "tts": {"max_duration": 15.0, "min_duration": 5.0},
            },
        )
        tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
        # 84 words at 2.5 wps = 33.6s — exceeds 15s max
        long_text = " ".join(["đây"] * 84)
        result = gen._validate_scene_duration(long_text, tts_cfg, wps=2.5)
        assert result is False

    def test_validate_scene_duration_fails_too_short(self):
        """Scene below min_duration returns False."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import TTSConfig
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["test"],
            channel_config={
                "name": "Test",
                "channel_id": "test",
                "characters": [{"name": "Mentor", "voice_id": "x"}],
                "watermark": {"text": "@Test", "enable": True, "font_size": 30, "opacity": 0.15, "motion": "bounce", "bounce_speed": 80, "bounce_padding": 20, "velocity_x": 1.2, "velocity_y": 0.8, "margin": 8},
                "style": "3D render",
                "research": {"niche_keywords": ["test"], "content_angle": "tips", "target_platform": "both", "research_interval_hours": 24, "pending_pool_size": 5, "threshold": 3},
                "tts": {"max_duration": 15.0, "min_duration": 5.0},
            },
        )
        tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
        # 5 words at 2.5 wps = 2s — below 5s min
        result = gen._validate_scene_duration("đây là test", tts_cfg, wps=2.5)
        assert result is False

    def test_regenerate_scene_tts_shortens_long_text(self):
        """_regenerate_scene_tts calls LLM and returns shorter text."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import TTSConfig
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["test"],
            channel_config={
                "name": "Test",
                "channel_id": "test",
                "characters": [{"name": "Mentor", "voice_id": "x"}],
                "watermark": {"text": "@Test", "enable": True, "font_size": 30, "opacity": 0.15, "motion": "bounce", "bounce_speed": 80, "bounce_padding": 20, "velocity_x": 1.2, "velocity_y": 0.8, "margin": 8},
                "style": "3D render",
                "research": {"niche_keywords": ["test"], "content_angle": "tips", "target_platform": "both", "research_interval_hours": 24, "pending_pool_size": 5, "threshold": 3},
                "tts": {"max_duration": 15.0, "min_duration": 5.0},
            },
        )
        tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
        long_text = " ".join(["đây là một từ dài"] * 20)  # ~100 words

        # Mock LLM provider that returns a shorter but valid-duration text
        # 20 words at 2.5 wps = 8s, within 5-15s bounds
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "đây là một từ dài đây là một từ dài đây là một từ dài đây là một từ dài"

        with patch("modules.llm.minimax.MiniMaxLLMProvider", return_value=mock_llm):
            result = gen._regenerate_scene_tts(long_text, tts_cfg, api_key="fake-key", wps=2.5)
        assert len(result.split()) < len(long_text.split()), f"expected shorter, got same length"
        mock_llm.chat.assert_called_once()
        # Verify result is within duration bounds (5-15s at 2.5 wps)
        word_count = len(result.split())
        estimated_duration = word_count / 2.5
        assert tts_cfg.min_duration <= estimated_duration <= tts_cfg.max_duration, (
            f"result still out of bounds: {estimated_duration:.1f}s ({word_count} words)"
        )

    def test_regenerate_scene_tts_exhausts_retries_and_returns_original(self):
        """After max_retries, falls back to original TTS."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import TTSConfig
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["test"],
            channel_config={
                "name": "Test",
                "channel_id": "test",
                "characters": [{"name": "Mentor", "voice_id": "x"}],
                "watermark": {"text": "@Test", "enable": True, "font_size": 30, "opacity": 0.15, "motion": "bounce", "bounce_speed": 80, "bounce_padding": 20, "velocity_x": 1.2, "velocity_y": 0.8, "margin": 8},
                "style": "3D render",
                "research": {"niche_keywords": ["test"], "content_angle": "tips", "target_platform": "both", "research_interval_hours": 24, "pending_pool_size": 5, "threshold": 3},
                "tts": {"max_duration": 15.0, "min_duration": 5.0},
            },
        )
        tts_cfg = TTSConfig(max_duration=15.0, min_duration=5.0)
        original = "đây là nguyên bản"

        # Mock LLM to always return 100 words (way over limit)
        mock_llm = MagicMock()
        mock_llm.chat.return_value = " ".join(["quá dài"] * 100)

        with patch("modules.llm.minimax.MiniMaxLLMProvider", return_value=mock_llm):
            result = gen._regenerate_scene_tts(original, tts_cfg, api_key="fake-key", wps=2.5, max_retries=3)
        assert result == original, f"expected original after retries, got: {result[:50]}"
        assert mock_llm.chat.call_count == 3, f"expected 3 calls, got {mock_llm.chat.call_count}"
