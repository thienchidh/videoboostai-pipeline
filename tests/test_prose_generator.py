"""Tests for prose generation in ContentIdeaGenerator."""
import pytest
from unittest.mock import MagicMock, patch


def test_prose_generator_has_build_prose_prompt():
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import ChannelConfig
    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["productivity"],
        channel_config=channel_cfg,
    )
    assert hasattr(gen, '_build_prose_prompt')
    assert hasattr(gen, '_parse_prose')


def test_prose_prompt_structure():
    from modules.content.content_idea_generator import ContentIdeaGenerator
    from modules.pipeline.models import ChannelConfig
    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["productivity"],
        channel_config=channel_cfg,
    )
    prompt = gen._build_prose_prompt(
        title="Test Title",
        keywords=["productivity"],
        angle="tips",
        description="Test description"
    )
    # Prompt should NOT use scene-based JSON structure
    assert '"scenes":' not in prompt
    assert '"scene_type":' not in prompt
    # Prompt should mention prose/storytelling format
    assert any(word in prompt.lower() for word in ["prose", "storytelling", "kịch bản", "đoạn văn"])


class TestParseProse:
    """Tests for _parse_prose method."""

    def test_parse_prose_strips_markdown_fences(self):
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import ChannelConfig
        channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["productivity"],
            channel_config=channel_cfg,
        )

        input_text = """```json
Đã bao giờ bạn cảm thấy một ngày có quá ít giờ để hoàn thành hết mọi việc? 🤔
Mình từng rất nhiều lần như vậy.
```
"""
        result = gen._parse_prose(input_text)
        assert "Đã bao giờ" in result
        assert "```" not in result

    def test_parse_prose_handles_plain_text(self):
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import ChannelConfig
        channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["productivity"],
            channel_config=channel_cfg,
        )

        input_text = """Đã bao giờ bạn cảm thấy một ngày có quá ít giờ?
Mình từng rất nhiều lần như vậy.
📌 Phương pháp 1: Time Blocking
📌 Phương pháp 2: Tắt thông báo
Bạn cũng nên thử! 💪"""
        result = gen._parse_prose(input_text)
        assert "Đã bao giờ" in result
        assert "Bạn cũng nên thử" in result

    def test_parse_prose_handles_partial_json(self):
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import ChannelConfig
        channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["productivity"],
            channel_config=channel_cfg,
        )

        # JSON-like with video_message should still return prose content
        input_text = '{"video_message": "test message"}\n\nĐã bao giờ bạn cảm thấy một ngày có quá ít giờ?'
        result = gen._parse_prose(input_text)
        assert "Đã bao giờ" in result

    def test_parse_prose_handles_empty_input(self):
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import ChannelConfig
        channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["productivity"],
            channel_config=channel_cfg,
        )

        result = gen._parse_prose("")
        assert result == ""

    def test_parse_prose_strips_scene_markers(self):
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import ChannelConfig
        channel_cfg = ChannelConfig.load("nang_suat_thong_minh")
        gen = ContentIdeaGenerator(
            project_id=1,
            content_angle="tips",
            niche_keywords=["productivity"],
            channel_config=channel_cfg,
        )

        # Lines starting with scene markers get stripped entirely
        input_text = """scene 1: Đã bao giờ bạn cảm thấy một ngày có quá ít giờ?
scene 2: Mình từng rất nhiều lần như vậy.
📌 Phương pháp 1: Time Blocking
Bạn cũng nên thử!"""
        result = gen._parse_prose(input_text)
        # Scene marker lines should be stripped
        assert "scene 1" not in result.lower()
        assert "scene 2" not in result.lower()
        # But actual prose content without scene markers should remain
        assert "📌" in result
        assert "Bạn cũng nên thử" in result


class TestGenerateScriptFromIdea:
    """Tests for generate_script_from_idea returning prose format."""

    def test_generate_script_from_idea_returns_script_field(self):
        """Result must have .script attribute (prose string), not .scenes."""
        import json
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import GenerationLLM, ChannelConfig

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.watermark = MagicMock(text="@test")
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
        gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            json.dumps({"video_message": "90-phút tốt hơn Pomodoro"}),
            """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%.
            📌 Phương pháp 1: Time Blocking 90 phút
            📌 Phương pháp 2: Quy tắc 2 phút
            Mình đã thử và thấy nó thay đổi hoàn toàn. Bạn cũng nên thử! 💪""",
        ]

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            result = gen.generate_script_from_idea({
                "title": "Test Title",
                "content_angle": "tips",
                "topic_keywords": ["productivity"]
            })

        # Must have .script attribute (prose string)
        assert hasattr(result, 'script')
        assert isinstance(result.script, str)
        assert len(result.script) > 20

        # Must NOT have .scenes attribute (that's scene-based format)
        assert not hasattr(result, 'scenes')

    def test_generate_script_from_idea_includes_video_message(self):
        """Result must have .video_message attribute populated."""
        import json
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import GenerationLLM

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.watermark = MagicMock(text="@test")
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
        gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            json.dumps({"video_message": "90-phút tốt hơn Pomodoro"}),
            """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%.
            📌 Phương pháp 1: Time Blocking 90 phút
            Bạn cũng nên thử! 💪""",
        ]

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            result = gen.generate_script_from_idea({
                "title": "Test Title",
                "content_angle": "tips",
                "topic_keywords": ["productivity"]
            })

        # video_message must be present and non-empty
        assert hasattr(result, 'video_message')
        assert isinstance(result.video_message, str)
        assert len(result.video_message) > 5
        assert "90-phút" in result.video_message

    def test_generate_script_from_idea_prose_has_hook(self):
        """Prose script must start with a hook/opener."""
        import json
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import GenerationLLM

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.watermark = MagicMock(text="@test")
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
        gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            json.dumps({"video_message": "90-phút tốt hơn Pomodoro"}),
            """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%.
            📌 Phương pháp 1: Time Blocking 90 phút
            📌 Phương pháp 2: Quy tắc 2 phút
            Mình đã thử và thấy nó thay đổi hoàn toàn. Bạn cũng nên thử! 💪""",
        ]

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            result = gen.generate_script_from_idea({
                "title": "Test Title",
                "content_angle": "tips",
                "topic_keywords": ["productivity"]
            })

        # Script should start with hook-like content
        assert result.script.startswith("Olympic") or result.script.startswith("Đã") or "Olympic" in result.script[:50]

    def test_generate_script_from_idea_prose_has_cta_emoji_markers(self):
        """Prose script must contain emoji markers like 📌 and 💪."""
        import json
        from modules.content.content_idea_generator import ContentIdeaGenerator
        from modules.pipeline.models import GenerationLLM

        mock_channel = MagicMock()
        mock_channel.name = "Test"
        mock_channel.style = "friendly"
        mock_channel.characters = [MagicMock(name="NamMinh", voice_id="x")]
        mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
        mock_channel.watermark = MagicMock(text="@test")
        mock_channel.image_style = MagicMock(
            lighting="warm", camera="eye-level", art_style="3D render",
            environment="office", composition="professional"
        )

        gen = ContentIdeaGenerator(project_id=1, channel_config=mock_channel)
        gen._llm = GenerationLLM(provider="minimax", model="MiniMax-M2.7", max_tokens=1536, retry_attempts=2, retry_backoff_max=5)

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = [
            json.dumps({"video_message": "90-phút tốt hơn Pomodoro"}),
            """Olympic không dùng Pomodoro 25-phút — họ dùng 90-phút và HIỆU QUẢ HƠN 40%.
            📌 Phương pháp 1: Time Blocking 90 phút
            📌 Phương pháp 2: Quy tắc 2 phút
            Mình đã thử và thấy nó thay đổi hoàn toàn. Bạn cũng nên thử! 💪""",
        ]

        with patch("modules.content.content_idea_generator.get_llm_provider", return_value=mock_llm):
            result = gen.generate_script_from_idea({
                "title": "Test Title",
                "content_angle": "tips",
                "topic_keywords": ["productivity"]
            })

        # Should contain 📌 marker for tips
        assert "📌" in result.script
        # Should contain 💪 or CTA closing
        assert "💪" in result.script or "bạn cũng nên" in result.script.lower()