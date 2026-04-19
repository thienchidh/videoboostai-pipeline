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
            "lighting": self.channel_style.lighting,
            "camera": self.channel_style.camera,
            "art_style": self.channel_style.art_style,
            "environment": self.channel_style.environment,
            "composition": self.channel_style.composition,
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
        """Get image prompt: use scene.image_prompt if present, else scene.video_prompt as fallback.

        For prose segments (no image_prompt/video_prompt), generates prompt from
        channel style + segment content.
        """
        if scene.image_prompt:
            return scene.image_prompt
        if scene.video_prompt:
            return scene.video_prompt
        # Prose segment — build prompt from channel style + segment content
        if self.channel_style and self.brand_tone:
            return self._build_prose_image_prompt(scene)
        return ""

    def _build_prose_image_prompt(self, scene: "SceneConfig") -> str:
        """Build image prompt for prose segments based on channel style and segment content."""
        # Extract first ~50 chars of script as context
        script_snippet = (scene.script or "")[:80].replace("\n", " ").strip()

        style_parts = []
        if self.channel_style.lighting:
            style_parts.append(f"{self.channel_style.lighting} lighting")
        if self.channel_style.camera:
            style_parts.append(f"{self.channel_style.camera} camera")
        if self.channel_style.art_style:
            style_parts.append(f"{self.channel_style.art_style} style")
        if self.channel_style.environment:
            style_parts.append(f"{self.channel_style.environment}")
        if self.channel_style.composition:
            style_parts.append(f"{self.channel_style.composition} composition")

        style_str = ", ".join(style_parts) if style_parts else "3D animated style"

        # Detect emotion from content
        emotion = "friendly"
        script_lower = script_snippet.lower()
        if any(word in script_lower for word in ["mình từng", "đã bao giờ", "bạn có"]):
            emotion = "curious and engaging"
        elif any(word in script_lower for word in ["📌", "phương pháp", "tip", "cách"]):
            emotion = "professional and informative"
        elif any(word in script_lower for word in ["💪", "thử", "bạn cũng"]):
            emotion = "motivating and inspiring"
        elif any(word in script_lower for word in ["🔔", "follow", "tips"]):
            emotion = "friendly and enthusiastic"

        return f"{style_str}, {emotion} emotion, {script_snippet}, high quality 3D render, vibrant colors"

    def get_lipsync_prompt(self, scene: "SceneConfig") -> str:
        """Get lipsync prompt: use scene.lipsync_prompt if present, else scene.video_prompt as fallback.

        For prose segments, falls back to channel config lipsync prompt.
        """
        if scene.lipsync_prompt:
            return scene.lipsync_prompt
        if scene.video_prompt:
            return scene.video_prompt
        # Prose segment — use default lipsync prompt from channel config
        return "A person talking confidently and professionally"
