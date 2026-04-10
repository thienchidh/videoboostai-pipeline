"""
modules/content/__init__.py — Content generation helpers

Provides:
- SceneGenerator: generates scene list from config
- ScriptGenerator: manages scripts per scene
"""

import re
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SceneGenerator:
    """Generate scene list from pipeline config."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def get_scenes(self) -> List[Dict[str, Any]]:
        """Return the list of scenes from config."""
        return self.config.get("scenes", [])

    def get_scene(self, scene_id: int) -> Optional[Dict[str, Any]]:
        """Get a single scene by its ID."""
        for scene in self.get_scenes():
            if scene.get("id") == scene_id:
                return scene
        return None

    def scene_count(self) -> int:
        """Total number of scenes."""
        return len(self.get_scenes())

    def get_characters(self) -> List[Dict[str, Any]]:
        """Return characters list from config."""
        return self.config.get("characters", [])


class ScriptGenerator:
    """Manage and expand scripts per scene."""

    FILLERS = [
        "Ừm... thật là",
        "Ôi... thú vị quá",
        "Bỗng nhiên... nào",
        "Này... nghe này",
        "Thật ra... mà",
        "Đẹp quá... nhỉ",
        "Vui ghê... hic",
        "Hay quá... đi",
        "Kỳ lạ... thật",
        "Lạ lắm... à"
    ]

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def get_script(self, scene: Dict[str, Any]) -> str:
        """Return the script text for a scene."""
        return scene.get("script", "")

    def get_characters_for_scene(self, scene: Dict[str, Any]) -> List[str]:
        """Return character names assigned to a scene."""
        return scene.get("characters", [])

    def expand_to_duration(self, script: str, min_duration: float = 5.0,
                           seconds_per_word: float = 0.3) -> str:
        """Expand script to meet minimum audio duration.

        Args:
            script: original script text
            min_duration: minimum duration in seconds
            seconds_per_word: estimated TTS seconds per word
        """
        words = script.split()
        estimated = len(words) * seconds_per_word
        if estimated >= min_duration:
            return script

        parts = re.split(r'([.!?])', script)
        sentences = []
        for i in range(0, len(parts) - 1, 2):
            sentences.append(parts[i] + parts[i + 1])
        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1])

        current_script = script
        filler_idx = 0
        while len(current_script.split()) * seconds_per_word < min_duration:
            filler = self.FILLERS[filler_idx % len(self.FILLERS)]
            filler_idx += 1
            if len(sentences) > 1:
                insert_pos = min(len(sentences) // 2, len(sentences) - 1)
                sentences.insert(insert_pos, f" {filler}...")
                current_script = ' '.join(sentences)
            else:
                current_script = f"{filler}... {current_script}"

        return current_script

    def split_for_multi_character(self, script: str,
                                   split_ratio: float = 0.6) -> tuple:
        """Split script for 2-character scenes. Returns (left_script, right_script)."""
        words = script.split()
        split_at = max(3, int(len(words) * split_ratio))
        left = " ".join(words[:split_at])
        right = " ".join(words[split_at:])
        return left, right

    def build_full_script(self, scenes: List[Dict[str, Any]]) -> str:
        """Combine all scene scripts into one full script string."""
        return " ".join(scene.get("script", "") for scene in scenes)
