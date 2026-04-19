import pytest
from modules.pipeline.scene_processor import ProseSegmenter


def test_split_by_paragraph():
    prose = "Hook question 🤔\n\n📌 Tip 1\nContent here\n\n📌 Tip 2\nMore content"
    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 2


def test_split_by_emoji_markers():
    prose = "Hook question 🤔\n📌 Phương pháp 1: Time Blocking\n📌 Phương pháp 2: 2 phút\nCTA 💪"
    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 3
    types = [s.segment_type for s in segments]
    assert "hook" in types
    assert "body" in types


def test_prose_segmenter_segment_types():
    prose = "Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔\n📌 Phương pháp 1\n📌 Phương pháp 2\nBạn cũng nên thử! 💪"
    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 2
    # First segment is hook
    assert segments[0].segment_type == "hook"
    # Last segment with 💪 is CTA
    cta_segments = [s for s in segments if s.segment_type == "cta"]
    assert len(cta_segments) >= 1


def test_prose_segmenter_handles_empty():
    segments = ProseSegmenter.split("")
    assert segments == []


def test_prose_segmenter_merges_short():
    prose = "Short"
    segments = ProseSegmenter.split(prose)
    # Should handle gracefully
    assert isinstance(segments, list)