"""tests/test_parallel_processor.py — Tests for ParallelSceneProcessor skip_image mode."""

import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Use absolute paths from the worktree root
import sys
WORKTREE_ROOT = Path(__file__).parent.parent.parent  # goes to .worktrees/skip-image-workflow
sys.path.insert(0, str(WORKTREE_ROOT))

from modules.pipeline.parallel_processor import ParallelSceneProcessor
from modules.pipeline.checkpoint import CheckpointHelper


def make_mock_ctx():
    """Minimal mock PipelineContext for ParallelSceneProcessor."""
    ctx = MagicMock()
    ctx.channel.tts.min_duration = 1.0
    ctx.channel.tts.max_duration = 30.0
    ctx.channel.characters = [
        MagicMock(name="TestChar", voice_id="default"),
    ]
    ctx.channel.voices = []
    ctx.channel.image_style = MagicMock()
    ctx.channel.image_style.lighting = "warm"
    ctx.channel.image_style.camera = "eye-level"
    ctx.channel.image_style.art_style = ""
    ctx.channel.image_style.environment = ""
    ctx.channel.image_style.composition = ""
    ctx.technical.generation.parallel_scene_processing.max_workers = 2
    return ctx


def test_skip_image_uses_placeholder_image():
    """When skip_image=True, phase 2 returns a placeholder image path without calling image_fn."""
    tmp = Path(tempfile.mkdtemp())
    try:
        placeholder = tmp / "scene.png"
        placeholder.write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')

        ctx = make_mock_ctx()
        proc = ParallelSceneProcessor(ctx, tmp, max_workers=2, skip_image=True)

        scenes = [{"id": 1, "characters": ["TestChar"]}]

        # image_fn should NOT be called when skip_image=True
        def fake_image_fn(prompt, path):
            raise AssertionError("image_fn should not be called when skip_image=True")

        results = proc._phase2_image_gen(scenes, fake_image_fn)
        assert results[1]["image_path"] is not None
        assert Path(results[1]["image_path"]).exists()
    finally:
        shutil.rmtree(tmp)


def test_skip_image_returns_gender_and_prompt():
    """skip_image mode still returns gender and prompt metadata."""
    tmp = Path(tempfile.mkdtemp())
    try:
        ctx = make_mock_ctx()
        proc = ParallelSceneProcessor(ctx, tmp, max_workers=2, skip_image=True)

        scenes = [{"id": 2, "characters": ["TestChar"]}]

        def fake_image_fn(prompt, path):
            raise AssertionError("image_fn should not be called")

        results = proc._phase2_image_gen(scenes, fake_image_fn)
        assert "gender" in results[2]
        assert "prompt" in results[2]
        assert results[2]["gender"] in ("male", "female")
    finally:
        shutil.rmtree(tmp)