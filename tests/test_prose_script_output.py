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