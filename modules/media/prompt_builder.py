"""
modules/media/prompt_builder.py — Style validator for generated prompts.

PromptBuilder checks whether image_prompt and lipsync_prompt strings
violate channel style constraints. It does NOT compose prompts.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from modules.pipeline.models import SceneConfig, ImageStyleConfig


class PromptBuilder:
    """Validate generated prompts against channel style constraints.

    Does NOT assemble prompts — LLM generates complete prompt strings.
    Simple fallback for YAML scenes without generated prompts:
        scene.image_prompt or scene.video_prompt or ""
    """

    def __init__(self, channel_style: Optional["ImageStyleConfig"] = None,
                 brand_tone: Optional[str] = None):
        self.channel_style = channel_style
        self.brand_tone = brand_tone

    def validate_image_prompt(self, image_prompt: Optional[str]) -> tuple[bool, list[str]]:
        """Validate image_prompt against channel style constraints.

        Returns (is_valid, violations):
          - is_valid: True if no violations found
          - violations: list of constraint names NOT found in the prompt
        """
        if not image_prompt:
            return False, ["image_prompt missing"]
        if not self.channel_style:
            return True, []  # no constraints to check

        violations = []
        prompt_lower = image_prompt.lower()

        constraints = {
            "lighting": getattr(self.channel_style, "lighting", None),
            "camera": getattr(self.channel_style, "camera", None),
            "art_style": getattr(self.channel_style, "art_style", None),
            "environment": getattr(self.channel_style, "environment", None),
            "composition": getattr(self.channel_style, "composition", None),
        }
        for name, value in constraints.items():
            if value and value.lower() not in prompt_lower:
                violations.append(name)

        return len(violations) == 0, violations

    def validate_lipsync_prompt(self, lipsync_prompt: Optional[str],
                                character_name: Optional[str] = None) -> tuple[bool, list[str]]:
        """Validate lipsync_prompt. Returns (is_valid, violations)."""
        if not lipsync_prompt:
            return False, ["lipsync_prompt missing"]
        violations = []
        if character_name and character_name.lower() not in lipsync_prompt.lower():
            violations.append("character_name_missing")
        return len(violations) == 0, violations

    def validate_creative_brief(self, brief: Optional[Dict[str, Any]]) -> tuple[bool, list[str]]:
        """Check creative_brief has sufficient depth for variety.

        Required fields: visual_concept, emotion, camera_mood, unique_angle.
        Optional: setting_vibe, action_description.

        Returns (is_valid, violations):
          - is_valid: True if all required fields are present
          - violations: list of required field names that are missing
        """
        if not brief:
            return False, ["creative_brief missing"]
        required_fields = ["visual_concept", "emotion", "camera_mood", "unique_angle"]
        violations = [f for f in required_fields if not brief.get(f)]
        return len(violations) == 0, violations

    def get_image_prompt(self, scene: "SceneConfig") -> str:
        """Get image prompt: use scene.image_prompt if present, else scene.video_prompt as fallback."""
        return scene.image_prompt or scene.video_prompt or ""

    def get_lipsync_prompt(self, scene: "SceneConfig") -> str:
        """Get lipsync prompt: use scene.lipsync_prompt if present, else scene.video_prompt as fallback."""
        return scene.lipsync_prompt or scene.video_prompt or ""
