"""
tests/test_caption_generator.py — Tests for CoT caption generator

Tests verify:
- GeneratedCaption dataclass has all required fields (including CoT fields)
- Strict field presence: LLM missing any field raises CaptionGenerationError
- Retry on JSON parse error: 1 retry then fail
- All 6 fields validated: thought_process, insight, headline, body, cta, hashtags
- Strict hashtag count: TikTok=5, Facebook=3
"""

import json
import pytest
from unittest.mock import MagicMock

from modules.content.caption_generator import GeneratedCaption, CaptionGenerator
from modules.pipeline.exceptions import CaptionGenerationError


# =============================================================================
# GeneratedCaption dataclass tests
# =============================================================================

def test_generated_caption_has_cot_fields():
    """GeneratedCaption must have thought_process and insight fields."""
    cap = GeneratedCaption(
        thought_process="Script nói về việc người thông minh làm ít hơn",
        insight="Người thông minh không làm nhiều hơn, họ làm khác hơn",
        headline="🔥 Bí quyết của người thông minh",
        body="Người thông minh không làm nhiều hơn, họ làm KHÁC hơn.",
        hashtags=["#nangsuat", "#thongminh"],
        cta="Bạn nghĩ sao? Comment nhé!",
        full_caption="🔥 Bí quyết...\nNgười thông minh...",
    )
    assert cap.thought_process == "Script nói về việc người thông minh làm ít hơn"
    assert cap.insight == "Người thông minh không làm nhiều hơn, họ làm khác hơn"
    assert "thông minh" in cap.insight or "không làm nhiều" in cap.insight


def test_generated_caption_to_dict_includes_cot_fields():
    """to_dict() must include thought_process and insight."""
    cap = GeneratedCaption(
        thought_process="test reasoning",
        insight="test insight",
        headline="🔥 Headline",
        body="Body text",
        hashtags=["#tag"],
        cta="CTA",
        full_caption="Full",
    )
    d = cap.to_dict()
    assert "thought_process" in d
    assert "insight" in d
    assert d["thought_process"] == "test reasoning"
    assert d["insight"] == "test insight"


# =============================================================================
# Strict field presence tests
# =============================================================================

def test_caption_generator_fails_when_llm_returns_incomplete_json_tiktok():
    """LLM returns JSON missing insight -> CaptionGenerationError raised."""
    mock_llm = MagicMock()
    # Returns valid JSON but missing 'insight' field
    mock_llm.chat.return_value = json.dumps({
        "thought_process": "Phân tích script",
        "headline": "🔥 Test",
        "body": "Body",
        "cta": "CTA",
        "hashtags": ["#a", "#b", "#c", "#d", "#e"],
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert "missing_field" in exc_info.value.reason
    assert "insight" in exc_info.value.reason


def test_caption_generator_fails_when_llm_returns_incomplete_json_facebook():
    """LLM returns JSON missing thought_process -> CaptionGenerationError raised."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({
        "insight": "Test insight",
        "headline": "**Test**",
        "body": "Body",
        "cta": "CTA",
        "hashtags": ["#a", "#b", "#c"],
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="facebook")
    assert "missing_field" in exc_info.value.reason
    assert "thought_process" in exc_info.value.reason


# =============================================================================
# Retry on JSON parse error tests
# =============================================================================

def test_caption_generator_retries_once_on_json_parse_error():
    """JSON parse fail on first attempt -> retry 1 time, second attempt succeeds."""
    mock_llm = MagicMock()
    # Lần 1: invalid JSON -> retry
    # Lần 2: valid complete JSON -> success
    mock_llm.chat.side_effect = [
        "this is not json at all",
        json.dumps({
            "thought_process": "Phân tích script",
            "insight": "Insight mạnh",
            "headline": "🔥 Test",
            "body": "Body",
            "cta": "CTA",
            "hashtags": ["#a", "#b", "#c", "#d", "#e"],
        }),
    ]

    gen = CaptionGenerator(llm_provider=mock_llm)
    cap = gen.generate("test script", platform="tiktok")

    assert mock_llm.chat.call_count == 2
    assert cap.thought_process == "Phân tích script"
    assert cap.insight == "Insight mạnh"
    assert cap.headline == "🔥 Test"


def test_caption_generator_fails_after_exhausted_retries():
    """Both attempts fail -> CaptionGenerationError with last error."""
    mock_llm = MagicMock()
    # Both attempts return invalid JSON
    mock_llm.chat.side_effect = ["bad1", "bad2"]

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert exc_info.value.reason == "json_parse_error"
    assert mock_llm.chat.call_count == 2


# =============================================================================
# Strict hashtag count tests
# =============================================================================

def test_caption_generator_fails_wrong_tiktok_hashtag_count():
    """TikTok requires exactly 5 hashtags, not 4 -> CaptionGenerationError."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({
        "thought_process": "x",
        "insight": "i",
        "headline": "🔥 Test",
        "body": "Body",
        "cta": "CTA",
        "hashtags": ["#a", "#b", "#c", "#d"],  # only 4
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert "invalid_field:hashtags" in exc_info.value.reason


def test_caption_generator_fails_wrong_facebook_hashtag_count():
    """Facebook requires exactly 3 hashtags, not 5 -> CaptionGenerationError."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({
        "thought_process": "x",
        "insight": "i",
        "headline": "**Test**",
        "body": "Body",
        "cta": "CTA",
        "hashtags": ["#a", "#b", "#c", "#d", "#e"],  # 5 instead of 3
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="facebook")
    assert "invalid_field:hashtags" in exc_info.value.reason


# =============================================================================
# All 6 fields required tests
# =============================================================================

def test_caption_generator_requires_all_six_fields():
    """Any of the 6 required fields missing -> fail with specific missing field."""
    required = ["thought_process", "insight", "headline", "body", "cta", "hashtags"]
    mock_llm = MagicMock()

    for missing_field in required:
        # Build a complete response then remove the one field
        full = {f: "x" for f in required}
        del full[missing_field]
        mock_llm.chat.return_value = json.dumps(full)
        gen = CaptionGenerator(llm_provider=mock_llm)
        with pytest.raises(CaptionGenerationError) as exc_info:
            gen.generate("test script", platform="tiktok")
        assert missing_field in exc_info.value.reason
        mock_llm.reset_mock()


# =============================================================================
# Success case tests
# =============================================================================

def test_caption_generator_success_tiktok():
    """Valid complete JSON -> returns GeneratedCaption with all fields."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({
        "thought_process": "Phân tích: điều bất ngờ là người thông minh làm ít hơn",
        "insight": "Người thông minh không làm nhiều hơn, họ làm khác hơn",
        "headline": "🔥 Bí quyết của người thông minh",
        "body": "Người thông minh không làm nhiều hơn, họ làm KHÁC hơn.",
        "cta": "Bạn nghĩ sao? Comment nhé!",
        "hashtags": ["#nangsuat", "#thongminh", "#cuocsong", "#thoigian", "#tuanlamviec"],
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    cap = gen.generate("test script", platform="tiktok")

    assert cap.thought_process == "Phân tích: điều bất ngờ là người thông minh làm ít hơn"
    assert cap.insight == "Người thông minh không làm nhiều hơn, họ làm khác hơn"
    assert cap.headline == "🔥 Bí quyết của người thông minh"
    assert cap.body == "Người thông minh không làm nhiều hơn, họ làm KHÁC hơn."
    assert len(cap.hashtags) == 5
    assert "🔥" in cap.headline
    # full_caption should be pre-formatted
    assert "🔥" in cap.full_caption


def test_caption_generator_success_facebook():
    """Valid complete JSON for Facebook -> returns GeneratedCaption with bold headline."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({
        "thought_process": "Phân tích",
        "insight": "Insight",
        "headline": " Bí quyết năng suất",
        "body": "Body text cho facebook",
        "cta": "Bạn nghĩ sao?",
        "hashtags": ["#nangsuat", "#cuocsong", "#tuanlamviec"],
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    cap = gen.generate("test script", platform="facebook")

    assert cap.thought_process == "Phân tích"
    assert cap.insight == "Insight"
    assert len(cap.hashtags) == 3
    # full_caption should not have fire emoji for facebook
    assert "**" in cap.full_caption or "👉" in cap.full_caption


# =============================================================================
# Empty field tests
# =============================================================================

def test_caption_generator_fails_on_empty_field():
    """Field is present but empty string -> CaptionGenerationError."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps({
        "thought_process": "",  # empty
        "insight": "i",
        "headline": "🔥 Test",
        "body": "Body",
        "cta": "CTA",
        "hashtags": ["#a", "#b", "#c", "#d", "#e"],
    })

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert "missing_field:thought_process" in exc_info.value.reason


# =============================================================================
# No fallback tests
# =============================================================================

def test_caption_generator_llm_exception_raises_caption_generation_error():
    """LLM raises Exception -> wrapped as CaptionGenerationError."""
    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("Network error")

    gen = CaptionGenerator(llm_provider=mock_llm)
    with pytest.raises(CaptionGenerationError) as exc_info:
        gen.generate("test script", platform="tiktok")
    assert isinstance(exc_info.value.original_error, RuntimeError)
