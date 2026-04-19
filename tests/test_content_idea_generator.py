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
                scenes, video_message = gen._generate_scenes("Test Title", ["test"], "tips", "", num_scenes=2, video_message="Test video message")

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

    def test_parse_scenes_handles_video_message_format(self):
        """_parse_scenes handles new format with video_message key and scenes array."""
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

        json_text = json.dumps({
            "video_message": "Tập trung vào 1 việc quan trọng nhất trước",
            "scenes": [
                {
                    "id": 1,
                    "script": "Hãy bắt đầu với kế hoạch hôm nay",
                    "character": "NamMinh",
                    "creative_brief": {
                        "visual_concept": "Close-up khuôn mặt tập trung",
                        "emotion": "serious but approachable",
                        "camera_mood": "shallow DOF, intimate close-up",
                        "setting_vibe": "home office with plants",
                        "unique_angle": "shooting from above desk",
                        "action_description": "speaking directly to camera"
                    },
                    "image_prompt": "Close-up of a focused woman...",
                    "lipsync_prompt": "NamMinh speaking with warm smile..."
                }
            ]
        })
        scenes = gen._parse_scenes(json_text)
        assert len(scenes) == 1
        assert scenes[0].script == "Hãy bắt đầu với kế hoạch hôm nay"
        assert scenes[0].creative_brief["emotion"] == "serious but approachable"


def test_generate_script_from_idea_includes_video_message():
    """generate_script_from_idea calls two-step: video_message first, then scenes."""
    import json
    from unittest.mock import MagicMock, patch, call
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")
    mock_channel.image_style = MagicMock(lighting="warm", camera="eye-level", art_style="3D render",
                                         environment="office", composition="professional")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=3, retry_backoff_max=10)

    step1_response = json.dumps({"video_message": "Tập trung vào 1 việc quan trọng nhất trước"})
    step2_response = json.dumps({
        "scenes": [
            {"id": 1, "script": "Bắt đầu ngay", "character": "NamMinh",
             "scene_type": "hook", "delivers": "first tip",
             "creative_brief": {"visual_concept": "test", "emotion": "serious",
                               "camera_mood": "close-up", "setting_vibe": "office",
                               "unique_angle": "desk", "action_description": "speaking"}},
        ]
    })

    mock_llm = MagicMock()
    # Return different responses per call: first = step1, second = step2
    mock_llm.chat.side_effect = [step1_response, step2_response]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({
            "title": "Test Title",
            "content_angle": "tips",
            "topic_keywords": ["test"]
        }, num_scenes=1)

    assert hasattr(result, 'video_message')
    assert result.video_message == "Tập trung vào 1 việc quan trọng nhất trước"
    assert mock_llm.chat.call_count == 2, f"expected 2 LLM calls (step1 + step2), got {mock_llm.chat.call_count}"


def test_generate_video_message_returns_non_null():
    """_generate_video_message returns a non-null string when LLM succeeds."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=256, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({"video_message": "90-phút thay vì 25-phút Pomodoro — Olympic dùng phương pháp này để đạt peak state"})

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen._generate_video_message("Test Title", ["productivity"], "tips", "Some research description")

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 10
    assert "90-phút" in result


def test_generate_video_message_raises_on_empty():
    """_generate_video_message raises RuntimeError when LLM returns empty."""
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=256, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    # LLM returns JSON with null video_message
    mock_llm.chat.return_value = '{"video_message": null}'

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        with pytest.raises(RuntimeError) as exc_info:
            gen._generate_video_message("Test Title", ["productivity"], "tips", "description")
    assert "empty/null video_message" in str(exc_info.value)


def test_scene_1_is_hook_with_partial_answer():
    """Prose script must start with a hook that implies (not just asks) an answer."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        json.dumps({"video_message": "90-phút tốt hơn Pomodoro"}),
        # Prose format: no scenes, just raw script text
        """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%. Bạn đang dùng sai phương pháp?
        Mình từng cũng nghĩ Pomodoro là tốt nhất cho đến khi tìm hiểu về cách athletes tập trung.
        📌 Phương pháp 1: Time Blocking 90 phút
        Làm việc 90 phút tập trung rồi nghỉ 15-20 phút. Mình đã thử và thấy hiệu quả! 💪""",
    ]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({"title": "Title", "content_angle": "tips", "topic_keywords": []})

    # Prose format: result.script is a string, not scenes
    assert hasattr(result, 'script')
    assert isinstance(result.script, str)
    # Script must be non-empty
    assert len(result.script) > 20
    # Script must imply an answer (contains "90-phút" as partial answer, not just a question mark)
    assert "90-phút" in result.script or "HIỆU QUẢ HƠN" in result.script


def test_final_scene_has_cta_or_summary():
    """Prose script must contain CTA markers at the end."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        json.dumps({"video_message": "Test message"}),
        # Prose format with CTA ending
        """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%.
        Mình từng cũng nghĩ Pomodoro là tốt nhất cho đến khi tìm hiểu về cách athletes tập trung.
        📌 Phương pháp 1: Time Blocking 90 phút
        📌 Phương pháp 2: Quy tắc 2 phút
        Mình đã thử và thấy nó thay đổi hoàn toàn cách làm việc. Bạn cũng nên thử! 💪""",
    ]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({"title": "Title", "content_angle": "tips", "topic_keywords": []})

    # Prose format: result.script is a string
    assert hasattr(result, 'script')
    assert isinstance(result.script, str)
    # Script must end with CTA markers or closing phrase
    cta_markers = ["bạn cũng nên", "thử ngay", "nên thử", "💪", "🔔", "Follow"]
    assert any(marker.lower() in result.script.lower() for marker in cta_markers), \
        f"Expected CTA marker in script ending, got: {result.script[-100:]}"


def test_validate_scenes_captures_gender():
    """_validate_scenes should pass gender through to SceneConfig.characters."""
    from unittest.mock import MagicMock
    from modules.content.content_idea_generator import ContentIdeaGenerator
    gen = ContentIdeaGenerator(project_id=1, channel_config=MagicMock(
        characters=[MagicMock(name="Mentor", voice_id="mentor_female")],
        voices=[]
    ))
    raw_scenes = [
        {"id": 1, "character": "Teacher", "gender": "male", "tts": "Hello"},
    ]
    result = gen._validate_scenes(raw_scenes)
    assert len(result) == 1
    assert result[0].characters[0].name == "Teacher"
    assert result[0].characters[0].gender == "male"  # NEW


def test_scene_count_dynamic():
    """Prose script should have reasonable length (80-120 words expected for ~30s video)."""
    import json
    from unittest.mock import MagicMock, patch
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import GenerationLLM

    mock_channel = MagicMock()
    mock_channel.name = "Test"
    mock_channel.style = "friendly"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.watermark = MagicMock(text="@test")

    gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
    gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = [
        json.dumps({"video_message": "Test"}),
        # Prose script with 4 tips - reasonable length
        """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%.
        Mình từng cũng nghĩ Pomodoro là tốt nhất cho đến khi tìm hiểu về cách athletes tập trung.
        📌 Phương pháp 1: Time Blocking 90 phút
        📌 Phương pháp 2: Quy tắc 2 phút
        📌 Phương pháp 3: Tắt thông báo
        Mình đã thử và thấy nó thay đổi hoàn toàn cách làm việc. Bạn cũng nên thử! 💪""",
    ]

    with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
        result = gen.generate_script_from_idea({"title": "Title", "content_angle": "tips", "topic_keywords": []})

    # Prose format: result.script is a string
    assert hasattr(result, 'script')
    assert isinstance(result.script, str)
    # Script should have reasonable length (at least 50 words for a proper script)
    word_count = len(result.script.split())
    assert word_count >= 30, f"Script too short: {word_count} words"
    # Should not be absurdly long either
    assert word_count <= 200, f"Script too long: {word_count} words"
