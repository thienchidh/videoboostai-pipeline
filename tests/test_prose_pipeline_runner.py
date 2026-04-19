import pytest
from unittest.mock import Mock, patch
from pathlib import Path

def test_prose_script_split_into_segments():
    """Test that prose script is split into logical segments."""
    from modules.pipeline.scene_processor import ProseSegmenter

    prose = "Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔\n\n📌 Phương pháp 1: Time Blocking\nChia ngày thành các khối 90 phút.\n\n📌 Phương pháp 2: Quy tắc 2 phút\nViệc dưới 2 phút → làm NGAY.\n\nBạn cũng nên thử! 💪"

    segments = ProseSegmenter.split(prose)
    assert len(segments) >= 2
    assert all(hasattr(s, 'script') for s in segments)
    assert all(hasattr(s, 'segment_type') for s in segments)