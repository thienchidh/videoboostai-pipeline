"""Tests for ContentIdeaGenerator."""
import pytest


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
