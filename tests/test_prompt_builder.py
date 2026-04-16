"""
tests/test_prompt_builder.py — Tests for PromptBuilder style validator.

Covers:
- SceneConfig.image_prompt and lipsync_prompt fields
- PromptBuilder.validate_image_prompt()
- PromptBuilder.validate_lipsync_prompt()
- PromptBuilder.get_image_prompt()
- PromptBuilder.get_lipsync_prompt()
- content_idea_generator._parse_scenes and _validate_scenes with new fields
"""

import pytest


# ─── SceneConfig field tests ──────────────────────────────────

def test_scene_config_image_prompt_field():
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, script="test", image_prompt="A speaker in office")
    assert scene.image_prompt == "A speaker in office"
    assert scene.lipsync_prompt is None


def test_scene_config_lipsync_prompt_field():
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=2, script="test", lipsync_prompt="NamMinh speaking clearly")
    assert scene.lipsync_prompt == "NamMinh speaking clearly"


def test_scene_config_from_dict_with_prompts():
    from modules.pipeline.models import SceneConfig
    data = {
        "id": 1,
        "script": "Hãy bắt đầu",
        "image_prompt": "A confident speaker in modern office",
        "lipsync_prompt": "Friendly speaker, NamMinh, vi-VN-NamMinhNeural"
    }
    scene = SceneConfig.from_dict(data)
    assert scene.image_prompt == "A confident speaker in modern office"
    assert scene.lipsync_prompt == "Friendly speaker, NamMinh, vi-VN-NamMinhNeural"


# ─── PromptBuilder.validate_image_prompt ──────────────────────

def test_validate_image_prompt_all_constraints_met():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import ImageStyleConfig
    style = ImageStyleConfig(
        lighting="warm",
        camera="eye-level",
        art_style="3D render",
        environment="modern office",
        composition="professional"
    )
    pb = PromptBuilder(channel_style=style)
    prompt = (
        "A professional speaker in modern office with warm lighting, "
        "eye-level camera, 3D render style, professional atmosphere"
    )
    is_valid, violations = pb.validate_image_prompt(prompt)
    assert is_valid is True
    assert violations == []


def test_validate_image_prompt_missing_constraints():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import ImageStyleConfig
    style = ImageStyleConfig(
        lighting="warm",
        camera="eye-level",
        art_style="3D render",
        environment="modern office",
        composition="professional"
    )
    pb = PromptBuilder(channel_style=style)
    # Missing "warm", "eye-level", "modern office", "professional"
    prompt = "Speaker in studio with 3D render style"
    is_valid, violations = pb.validate_image_prompt(prompt)
    assert is_valid is False
    assert "lighting" in violations
    assert "camera" in violations
    assert "art_style" not in violations  # present
    assert "environment" in violations
    assert "composition" in violations


def test_validate_image_prompt_no_style_config():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder(channel_style=None)
    is_valid, violations = pb.validate_image_prompt("any prompt")
    assert is_valid is True
    assert violations == []


def test_validate_image_prompt_missing():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    is_valid, violations = pb.validate_image_prompt(None)
    assert is_valid is False
    assert "image_prompt missing" in violations


# ─── PromptBuilder.validate_lipsync_prompt ────────────────────

def test_validate_lipsync_prompt_with_character():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    prompt = "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly"
    is_valid, violations = pb.validate_lipsync_prompt(prompt, character_name="NamMinh")
    assert is_valid is True
    assert violations == []


def test_validate_lipsync_prompt_missing_character():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    prompt = "Friendly speaker talking clearly"
    is_valid, violations = pb.validate_lipsync_prompt(prompt, character_name="NamMinh")
    assert is_valid is False
    assert "character_name_missing" in violations


def test_validate_lipsync_prompt_missing():
    from modules.media.prompt_builder import PromptBuilder
    pb = PromptBuilder()
    is_valid, violations = pb.validate_lipsync_prompt(None)
    assert is_valid is False
    assert "lipsync_prompt missing" in violations


# ─── PromptBuilder.get_image_prompt ──────────────────────────

def test_get_image_prompt_uses_scene_field():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, image_prompt="A confident speaker in modern office")
    pb = PromptBuilder()
    assert pb.get_image_prompt(scene) == "A confident speaker in modern office"


def test_get_image_prompt_fallback_to_video_prompt():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, video_prompt="A studio background")
    pb = PromptBuilder()
    assert pb.get_image_prompt(scene) == "A studio background"


def test_get_image_prompt_empty_when_both_none():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1)
    pb = PromptBuilder()
    assert pb.get_image_prompt(scene) == ""


# ─── PromptBuilder.get_lipsync_prompt ─────────────────────────

def test_get_lipsync_prompt_uses_scene_field():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, lipsync_prompt="NamMinh speaking with warm smile")
    pb = PromptBuilder()
    assert pb.get_lipsync_prompt(scene) == "NamMinh speaking with warm smile"


def test_get_lipsync_prompt_fallback_to_video_prompt():
    from modules.media.prompt_builder import PromptBuilder
    from modules.pipeline.models import SceneConfig
    scene = SceneConfig(id=1, video_prompt="A person talking")
    pb = PromptBuilder()
    assert pb.get_lipsync_prompt(scene) == "A person talking"


# ─── content_idea_generator._parse_scenes ─────────────────────

def test_parse_scenes_includes_image_and_lipsync_prompts():
    import json
    from unittest.mock import MagicMock
    from modules.content.content_idea_generator import ContentIdeaGenerator

    # Use mocks so we don't hit the filesystem
    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.style = "chuyên gia thân thiện"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.image_style = MagicMock(
        lighting="warm", camera="eye-level", art_style="3D render",
        environment="office", composition="professional"
    )

    gen = ContentIdeaGenerator(channel_config=mock_channel)

    json_text = json.dumps([{
        "id": 1,
        "script": "Hãy bắt đầu với kế hoạch hôm nay",
        "background": "văn phòng hiện đại",
        "character": "NamMinh",
        "image_prompt": "A confident professional speaker in modern office, warm lighting, eye-level camera, 3D render style, professional atmosphere",
        "lipsync_prompt": "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly, gesturing while explaining"
    }])
    scenes = gen._parse_scenes(json_text)
    assert len(scenes) == 1
    assert scenes[0]["image_prompt"] == "A confident professional speaker in modern office, warm lighting, eye-level camera, 3D render style, professional atmosphere"
    assert scenes[0]["lipsync_prompt"] == "Friendly speaker, NamMinh, vi-VN-NamMinhNeural, smiling warmly, gesturing while explaining"


def test_validate_scenes_normalizes_image_and_lipsync_prompts():
    from unittest.mock import MagicMock
    from modules.content.content_idea_generator import ContentIdeaGenerator

    mock_channel = MagicMock()
    mock_channel.name = "Test Channel"
    mock_channel.style = "test"
    mock_channel.characters = [MagicMock(name="NamMinh", voice_id="vi-VN-NamMinhNeural")]
    mock_channel.tts = MagicMock(max_duration=15.0, min_duration=5.0)
    mock_channel.image_style = MagicMock()

    gen = ContentIdeaGenerator(channel_config=mock_channel)

    # Scene with None values should normalize to None
    scenes = gen._validate_scenes([{
        "id": 1,
        "script": "Test",
        "character": "NamMinh",
        "image_prompt": None,
        "lipsync_prompt": None
    }])
    assert scenes[0]["image_prompt"] is None
    assert scenes[0]["lipsync_prompt"] is None

    # Scene missing both keys entirely
    scenes = gen._validate_scenes([{
        "id": 2,
        "script": "Test 2",
        "character": "NamMinh"
    }])
    # Missing keys should normalize to None (not KeyError)
    assert scenes[1]["image_prompt"] is None
    assert scenes[1]["lipsync_prompt"] is None
