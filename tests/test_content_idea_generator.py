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

    def test_generate_scenes_validates_duration_and_regenerates(self):
        """Scenes too long are regenerated before being returned."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import TTSConfig, GenerationLLM, ChannelConfig
        from unittest.mock import MagicMock, patch
        import json

        channel_cfg = ChannelConfig(
            channel_id="test",
            name="Test",
            characters=[{"name": "Mentor", "voice_id": "x"}],
            watermark={"text": "@Test", "enable": True, "font_size": 30, "opacity": 0.15, "motion": "bounce", "bounce_speed": 80, "bounce_padding": 20, "velocity_x": 1.2, "velocity_y": 0.8, "margin": 8},
            style="3D render",
            research={"niche_keywords": ["test"], "content_angle": "tips", "target_platform": "both", "research_interval_hours": 24, "pending_pool_size": 5, "threshold": 3},
            tts={"max_duration": 15.0, "min_duration": 5.0},
        )
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["test"],
            channel_config=channel_cfg,
        )

        # Set _llm so _generate_scenes doesn't raise ConfigMissingKeyError
        gen._llm = GenerationLLM(
            provider="minimax",
            model="MiniMax-M2.7",
            max_tokens=1536,
            retry_attempts=3,
            retry_backoff_max=10,
        )

        # Mock _technical_config to provide wps
        mock_tech_config = MagicMock()
        mock_gen = MagicMock()
        mock_tts_cfg = MagicMock()
        mock_tts_cfg.words_per_second = 2.5
        mock_gen.tts = mock_tts_cfg
        mock_tech_config.generation = mock_gen
        gen._technical_config = mock_tech_config

        # Mock LLM provider chain: get_llm_provider returns mock LLM
        # whose chat() returns a scene that's too long (80 words = 32s at 2.5 wps)
        long_scene = {"id": 1, "tts": " ".join(["đây là một từ dài"] * 40), "character": "Mentor", "background": "office, 3D render"}
        short_scene = {"id": 2, "tts": "ngắn gọn", "character": "Mentor", "background": "office, 3D render"}
        mock_llm = MagicMock()
        mock_llm.chat.return_value = json.dumps([long_scene, short_scene])

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            with patch.object(gen, "_regenerate_scene_tts", return_value="ngắn gọn và đúng vào việc thôi"):
                scenes = gen._generate_scenes("Test Title", ["test"], "tips", "", num_scenes=2)

        assert len(scenes) == 2
        # The too-long scene should have been regenerated
        assert scenes[0].tts == "ngắn gọn và đúng vào việc thôi"

    def test_validate_scene_duration_skips_when_no_tts_config(self):
        """When channel config has no tts, validation returns True (skip)."""
        from modules.content.content_idea_generator import ContentIdeaGenerator
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
                # no "tts" key — simulating channel config without TTS bounds
            },
        )
        # Should not raise — returns True (skip validation) when tts_cfg is None
        result = gen._validate_scene_duration("some text that is definitely way too long " * 10, None, wps=2.5)
        assert result is True

    def test_parse_scenes_includes_creative_brief(self):
        import json
        from unittest.mock import MagicMock
        from modules.content.content_idea_generator import ContentIdeaGenerator

        mock_channel = MagicMock()
        mock_channel.name = "Test Channel"
        mock_channel.style = "chuyên gia thân thiện"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(channel_config=mock_channel)

        json_text = json.dumps([{
            "id": 1,
            "script": "Hãy bắt đầu với kế hoạch hôm nay",
            "character": "NamMinh",
            "creative_brief": {
                "visual_concept": "Close-up khuôn mặt tập trung",
                "emotion": "serious but approachable",
                "camera_mood": "shallow DOF, intimate close-up",
                "setting_vibe": "home office with plants",
                "unique_angle": "shooting from above desk, papers visible",
                "action_description": "speaking directly to camera"
            },
            "image_prompt": "Close-up of a focused woman at a desk...",
            "lipsync_prompt": "NamMinh speaking with warm smile..."
        }])
        scenes = gen._parse_scenes(json_text)
        assert len(scenes) == 1
        assert scenes[0].creative_brief is not None
        assert scenes[0].creative_brief["emotion"] == "serious but approachable"
        assert scenes[0].creative_brief["unique_angle"] == "shooting from above desk, papers visible"
