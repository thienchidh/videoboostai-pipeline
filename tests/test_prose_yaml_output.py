import pytest
from pathlib import Path
import tempfile, yaml

def test_save_script_config_writes_prose_format():
    from modules.content.content_pipeline import ContentPipeline
    from modules.pipeline.models import ScriptOutput
    from unittest.mock import patch, Mock

    # Create a temp script output
    script = ScriptOutput(
        title="Test Prose Script",
        script="Đã bao giờ bạn cảm thấy một ngày có quá ít giờ? 🤔\n\n📌 Phương pháp 1: Time Blocking\nChia ngày thành các khối 90 phút.",
        video_message="Phương pháp 90-phút giúp deep work hiệu quả hơn 40%"
    )

    # Mock pipeline to call _save_script_config
    with patch.object(ContentPipeline, '__init__', lambda self, **kw: None):
        pipeline = ContentPipeline.__new__(ContentPipeline)
        pipeline.project_root = Path(tempfile.mkdtemp())
        pipeline.channel_id = "test_channel"

        result = pipeline._save_script_config(123, script)

    with open(result, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "script" in data
    assert "scenes" not in data
    assert "video_message" in data
    assert "title" in data
    assert data["title"] == "Test Prose Script"
    assert "📌" in data["script"]