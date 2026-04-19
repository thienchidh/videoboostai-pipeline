"""Tests for prose generation in ContentIdeaGenerator."""
import pytest


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