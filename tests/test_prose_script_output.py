import pytest

def test_script_output_has_script_field():
    from modules.pipeline.models import ScriptOutput
    output = ScriptOutput(
        title="Test Title",
        script="Đây là script prose với emoji 📌 và nhiều dòng.\n\nDòng thứ hai.",
        video_message="Test message"
    )
    assert hasattr(output, "script")
    assert output.script == "Đây là script prose với emoji 📌 và nhiều dòng.\n\nDòng thứ hai."

def test_script_output_no_scenes():
    from modules.pipeline.models import ScriptOutput
    output = ScriptOutput(
        title="Test",
        script="Prose script",
        video_message="Message"
    )
    # Verify no scenes attribute
    assert not hasattr(output, "scenes") or output.scenes is None


def test_prose_segment_model():
    from modules.pipeline.models import ProseSegment
    seg = ProseSegment(
        index=0,
        script="Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔",
        segment_type="hook"
    )
    assert seg.index == 0
    assert "Đã bao giờ" in seg.script
    assert seg.segment_type == "hook"


def test_prose_segment_defaults():
    from modules.pipeline.models import ProseSegment
    seg = ProseSegment(index=1, script="📌 Phương pháp 1: Time Blocking")
    assert seg.segment_type == "body"  # default
    assert seg.tts_text == ""  # default