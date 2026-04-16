"""Tests for scene_checkpoint.py - StepCheckpointWriter and step resume logic."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Import the module under test
from modules.pipeline.scene_checkpoint import (
    STEP_NAMES,
    StepCheckpointWriter,
    _get_first_incomplete_step,
    _now_iso,
    _step_file,
)


class TestStepFile:
    """Tests for _step_file helper."""

    def test_step_file_format(self, tmp_path):
        """Step files are named step_XX_name.json."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        result = _step_file(scene_dir, 1)
        assert result.name == "step_01_tts.json"
        assert result.parent == scene_dir

    def test_step_file_all_steps(self, tmp_path):
        """All 4 steps produce correctly named files."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        for step_num, expected_name in [
            (1, "step_01_tts.json"),
            (2, "step_02_image.json"),
            (3, "step_03_lipsync.json"),
            (4, "step_04_crop.json"),
        ]:
            assert _step_file(scene_dir, step_num).name == expected_name


class TestGetFirstIncompleteStep:
    """Tests for _get_first_incomplete_step - identifies first non-done step (1-5)."""

    def test_all_missing_returns_1(self, tmp_path):
        """No step files → first incomplete is 1."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        assert _get_first_incomplete_step(scene_dir) == 1

    def test_step_01_done_returns_2(self, tmp_path):
        """Step 1 done → first incomplete is 2."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        step_file = _step_file(scene_dir, 1)
        step_file.write_text(json.dumps({"status": "done"}))
        assert _get_first_incomplete_step(scene_dir) == 2

    def test_steps_01_02_done_returns_3(self, tmp_path):
        """Steps 1+2 done → first incomplete is 3."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        _step_file(scene_dir, 1).write_text(json.dumps({"status": "done"}))
        _step_file(scene_dir, 2).write_text(json.dumps({"status": "done"}))
        assert _get_first_incomplete_step(scene_dir) == 3

    def test_retry_step_returns_that_step(self, tmp_path):
        """A 'retry' status step is considered incomplete."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        _step_file(scene_dir, 1).write_text(json.dumps({"status": "done"}))
        _step_file(scene_dir, 2).write_text(json.dumps({"status": "retry"}))
        assert _get_first_incomplete_step(scene_dir) == 2

    def test_missing_step_after_done_returns_that_step(self, tmp_path):
        """Step 1 done, step 2 missing → first incomplete is 2."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        _step_file(scene_dir, 1).write_text(json.dumps({"status": "done"}))
        assert _get_first_incomplete_step(scene_dir) == 2

    def test_all_done_returns_5(self, tmp_path):
        """All 4 steps done → returns 5 (all complete)."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        for i in range(1, 5):
            _step_file(scene_dir, i).write_text(json.dumps({"status": "done"}))
        assert _get_first_incomplete_step(scene_dir) == 5


class TestStepCheckpointWriter:
    """Tests for StepCheckpointWriter - writes step_XX_*.json checkpoint files."""

    def test_write_tts_checkpoint(self, tmp_path):
        """write_tts writes step_01_tts.json with all expected fields."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_tts(
            output="/tmp/scene_1/audio_tts.mp3",
            duration_seconds=12.5,
            text="Hôm nay chúng ta...",
            provider="edge",
            voice="vi-VN-NamMinhNeural",
            speed=1.0,
            model="edge-tts",
            sample_rate=32000,
            bitrate="128k",
            format="mp3",
        )

        step_file = _step_file(scene_dir, 1)
        assert step_file.exists()
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["step"] == 1
        assert data["name"] == "tts"
        assert data["status"] == "done"
        assert data["mode"] == "edge"
        assert data["output"] == "/tmp/scene_1/audio_tts.mp3"
        assert data["duration_seconds"] == 12.5
        assert data["text"] == "Hôm nay chúng ta..."
        assert data["provider"] == "edge"
        assert data["voice"] == "vi-VN-NamMinhNeural"
        assert data["speed"] == 1.0
        assert data["model"] == "edge-tts"
        assert data["sample_rate"] == 32000
        assert data["bitrate"] == "128k"
        assert data["format"] == "mp3"
        assert data["error"] is None
        assert "created_at" in data

    def test_write_tts_with_error(self, tmp_path):
        """write_tts records error field when provided."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_tts(
            output="/tmp/scene_1/audio_tts.mp3",
            duration_seconds=12.5,
            text="Hôm nay chúng ta...",
            provider="edge",
            voice="vi-VN-NamMinhNeural",
            speed=1.0,
            model="edge-tts",
            sample_rate=32000,
            bitrate="128k",
            format="mp3",
            error="Connection timeout after 30s",
        )

        step_file = _step_file(scene_dir, 1)
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["error"] == "Connection timeout after 30s"

    def test_write_image_checkpoint(self, tmp_path):
        """write_image writes step_02_image.json with all expected fields."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_image(
            output="/tmp/scene_1/image.png",
            input_text="A sunset over the ocean",
            input_duration=15.0,
            prompt="A beautiful sunset over the ocean, cinematic lighting",
            provider="minimax",
            model="image-v2",
            aspect_ratio="16:9",
            gender="female",
            character_name="Linda",
            timeout=120,
            poll_interval=10,
            max_polls=12,
        )

        step_file = _step_file(scene_dir, 2)
        assert step_file.exists()
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["step"] == 2
        assert data["name"] == "image"
        assert data["status"] == "done"
        assert data["output"] == "/tmp/scene_1/image.png"
        assert data["input_text"] == "A sunset over the ocean"
        assert data["input_duration"] == 15.0
        assert data["prompt"] == "A beautiful sunset over the ocean, cinematic lighting"
        assert data["provider"] == "minimax"
        assert data["model"] == "image-v2"
        assert data["aspect_ratio"] == "16:9"
        assert data["gender"] == "female"
        assert data["character_name"] == "Linda"
        assert data["timeout"] == 120
        assert data["poll_interval"] == 10
        assert data["max_polls"] == 12
        assert data["error"] is None
        assert "created_at" in data

    def test_write_image_with_error(self, tmp_path):
        """write_image records error field when provided."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_image(
            output="/tmp/scene_1/image.png",
            input_text="A sunset over the ocean",
            input_duration=15.0,
            prompt="A beautiful sunset over the ocean, cinematic lighting",
            provider="minimax",
            model="image-v2",
            aspect_ratio="16:9",
            gender="female",
            character_name="Linda",
            timeout=120,
            poll_interval=10,
            max_polls=12,
            error="API rate limit exceeded",
        )

        step_file = _step_file(scene_dir, 2)
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["error"] == "API rate limit exceeded"

    def test_write_lipsync_checkpoint_with_fallback(self, tmp_path):
        """write_lipsync writes step_03_lipsync.json including fallback fields."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_lipsync(
            output="/tmp/scene_1/lipsync.mp4",
            input_image="/tmp/scene_1/image.png",
            input_audio="/tmp/scene_1/audio_tts.mp3",
            input_duration=12.5,
            prompt="Talking head video of a person",
            provider="wavespeed",
            actual_mode="static",
            attempted_mode="lipsync",
            fallback_reason="LipsyncQuotaError: credits exhausted",
            resolution="1080x1920",
            max_wait=900,
            poll_interval=10,
            retries=3,
            task_id="task_12345",
            job_id="job_67890",
            api_request_payload={"model": "infinitalk"},
            api_response={"status": "completed"},
        )

        step_file = _step_file(scene_dir, 3)
        assert step_file.exists()
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["step"] == 3
        assert data["name"] == "lipsync"
        assert data["status"] == "done"
        assert data["output"] == "/tmp/scene_1/lipsync.mp4"
        assert data["input_image"] == "/tmp/scene_1/image.png"
        assert data["input_audio"] == "/tmp/scene_1/audio_tts.mp3"
        assert data["input_duration"] == 12.5
        assert data["prompt"] == "Talking head video of a person"
        assert data["provider"] == "wavespeed"
        assert data["actual_mode"] == "static"
        assert data["attempted_mode"] == "lipsync"
        assert data["fallback_reason"] == "LipsyncQuotaError: credits exhausted"
        assert data["resolution"] == "1080x1920"
        assert data["max_wait"] == 900
        assert data["poll_interval"] == 10
        assert data["retries"] == 3
        assert data["task_id"] == "task_12345"
        assert data["job_id"] == "job_67890"
        assert data["api_request_payload"] == {"model": "infinitalk"}
        assert data["api_response"] == {"status": "completed"}
        assert data["error"] is None
        assert "created_at" in data

    def test_write_lipsync_without_optional_fields(self, tmp_path):
        """write_lipsync works without optional task_id/job_id."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_lipsync(
            output="/tmp/scene_1/lipsync.mp4",
            input_image="/tmp/scene_1/image.png",
            input_audio="/tmp/scene_1/audio_tts.mp3",
            input_duration=12.5,
            prompt="Talking head video of a person",
            provider="wavespeed",
            actual_mode="lipsync",
            attempted_mode="lipsync",
            fallback_reason=None,
            resolution="1080x1920",
            max_wait=900,
            poll_interval=10,
            retries=3,
        )

        step_file = _step_file(scene_dir, 3)
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["task_id"] is None
        assert data["job_id"] is None
        assert data["api_request_payload"] is None
        assert data["api_response"] is None

    def test_write_crop_checkpoint(self, tmp_path):
        """write_crop writes step_04_crop.json with all expected fields."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_crop(
            output="/tmp/scene_1/video_cropped.mp4",
            input="/tmp/scene_1/lipsync.mp4",
            input_duration=12.5,
            input_width=1080,
            input_height=1920,
            input_ratio=0.5625,
            output_width=1080,
            output_height=1920,
            output_duration=12.5,
            crop_filter="crop=1080:1920:0:0",
            scale_filter="scale=1080:1920",
            ffmpeg_cmd="ffmpeg -i input.mp4 -vf crop...",
            codec="libx264",
            crf=23,
            preset="medium",
        )

        step_file = _step_file(scene_dir, 4)
        assert step_file.exists()
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["step"] == 4
        assert data["name"] == "crop"
        assert data["status"] == "done"
        assert data["output"] == "/tmp/scene_1/video_cropped.mp4"
        assert data["input"] == "/tmp/scene_1/lipsync.mp4"
        assert data["input_duration"] == 12.5
        assert data["input_width"] == 1080
        assert data["input_height"] == 1920
        assert data["input_ratio"] == 0.5625
        assert data["output_width"] == 1080
        assert data["output_height"] == 1920
        assert data["output_duration"] == 12.5
        assert data["crop_filter"] == "crop=1080:1920:0:0"
        assert data["scale_filter"] == "scale=1080:1920"
        assert data["ffmpeg_cmd"] == "ffmpeg -i input.mp4 -vf crop..."
        assert data["codec"] == "libx264"
        assert data["crf"] == 23
        assert data["preset"] == "medium"
        assert data["error"] is None
        assert "created_at" in data

    def test_write_crop_with_error(self, tmp_path):
        """write_crop records error field when provided."""
        scene_dir = tmp_path / "scene_001"
        scene_dir.mkdir()
        writer = StepCheckpointWriter(scene_dir, "scene_001")

        writer.write_crop(
            output="/tmp/scene_1/video_cropped.mp4",
            input="/tmp/scene_1/lipsync.mp4",
            input_duration=12.5,
            input_width=1080,
            input_height=1920,
            input_ratio=0.5625,
            output_width=1080,
            output_height=1920,
            output_duration=12.5,
            crop_filter="crop=1080:1920:0:0",
            scale_filter="scale=1080:1920",
            ffmpeg_cmd="ffmpeg -i input.mp4 -vf crop...",
            codec="libx264",
            crf=23,
            preset="medium",
            error="FFmpeg encode failed: invalid codec",
        )

        step_file = _step_file(scene_dir, 4)
        data = json.loads(step_file.read_text(encoding="utf-8"))
        assert data["error"] == "FFmpeg encode failed: invalid codec"
