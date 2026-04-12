#!/usr/bin/env python3
"""
content_idea_generator.py - Generate content ideas and video scripts from topics.

Uses LLM providers via modules.llm.get_llm_provider().
Easy to swap: set llm.provider in config (minimax | openai | anthropic | ...).
"""

import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from modules.llm import get_llm_provider

logger = logging.getLogger(__name__)


class ContentIdeaGenerator:
    """Generate content ideas and video scripts from research topics.

    Uses LLM to generate scene scripts — no hardcoded templates.
    Swappable LLM backend via PluginRegistry (modules/llm/).
    """

    def __init__(self, project_id: int = None, target_platform: str = "both",
                 content_angle: str = "tips", niche_keywords: List[str] = None,
                 llm_config: Optional[Dict] = None,
                 channel_config: Optional[Dict] = None):
        """
        Args:
            project_id: project ID for DB storage
            target_platform: 'facebook', 'tiktok', or 'both'
            content_angle: 'tips', 'educational', 'motivational', 'story'
            niche_keywords: list of niche keywords
            llm_config: Optional dict with 'provider', 'model', 'api_key' keys.
                         If None, resolves from config automatically.
            channel_config: Optional channel config dict for characters and TTS limits.
                           If None, no character/TTS context is included in prompt.
        """
        self.project_id = project_id
        self.target_platform = target_platform
        self.content_angle = content_angle
        self.niche_keywords = niche_keywords or ["productivity", "time management", "năng suất"]
        self._llm_config = llm_config or {}
        self._channel_config = channel_config or {}

    def generate_ideas_from_topics(self, topics: List[Dict], count: int = 5) -> List[Dict]:
        """Generate content ideas from researched topics."""
        ideas = []
        for topic in topics[:count]:
            idea = {
                "title": topic.get("title", ""),
                "description": topic.get("summary", ""),
                "topic_keywords": topic.get("keywords", []),
                "content_angle": self.content_angle,
                "target_platform": self.target_platform,
                "source": topic.get("source_keyword", "unknown"),
                "status": "raw",
                "created_at": datetime.now().isoformat()
            }
            ideas.append(idea)
        return ideas

    def generate_script_from_idea(self, idea: Dict, num_scenes: int = 3) -> Dict:
        """
        Generate scene scripts from a content idea.
        Returns scene scripts in video_pipeline format.
        """
        title = idea.get("title", "")
        keywords = idea.get("topic_keywords", [])
        angle = idea.get("content_angle", self.content_angle)

        scenes = self._generate_scenes(title, keywords, angle, num_scenes)

        return {
            "title": title,
            "content_angle": angle,
            "keywords": keywords,
            "scenes": scenes,
            "watermark": "@NangSuatThongMinh",
            "style": "3D animated Pixar Disney style, high quality 3D render, vibrant colors, smooth animation",
            "generated_at": datetime.now().isoformat()
        }

    def _generate_scenes(self, title: str, keywords: List[str], angle: str,
                          num_scenes: int = 3) -> List[Dict]:
        """Generate scene scripts using LLM provider.

        Raises:
            RuntimeError: if LLM call fails or returns no valid scenes.
        """
        api_key = self._llm_config.get("api_key", "") if self._llm_config else ""
        if not api_key:
            # Resolve from technical config directly
            from pathlib import Path
            import yaml
            from core.paths import PROJECT_ROOT
            tech_cfg_path = PROJECT_ROOT / "configs" / "technical" / "config_technical.yaml"
            if not tech_cfg_path.exists():
                raise RuntimeError("Technical config not found - cannot resolve LLM API key")
            with open(tech_cfg_path, encoding="utf-8") as f:
                tech_cfg = yaml.safe_load(f)
            api_key = tech_cfg.get("api", {}).get("keys", {}).get("minimax", "")
            if not api_key:
                raise RuntimeError("minimax API key not found in technical config")

        llm = get_llm_provider(
            name=self._llm_config.get("provider", "minimax") if self._llm_config else "minimax",
            api_key=api_key,
            model=self._llm_config.get("model", "MiniMax-M2.7") if self._llm_config else "MiniMax-M2.7",
        )
        prompt = self._build_scene_prompt(title, keywords, angle, num_scenes)
        text = llm.chat(prompt, max_tokens=1536)
        scenes = self._parse_scenes(text)
        if not scenes:
            raise RuntimeError(f"LLM returned no valid scenes for title: {title}")
        return scenes

    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             num_scenes: int) -> str:
        """Build the prompt sent to LLM for scene generation."""
        kw_str = ", ".join(keywords) if keywords else "productivity, time management"

        # Build character context from channel config
        char_context = ""
        if self._channel_config:
            chars = self._channel_config.get("characters", [])
            if chars:
                char_lines = []
                for c in chars:
                    name = c.get("name", "Unknown")
                    voice_id = c.get("voice_id", "")
                    char_lines.append(f"  - {name} (voice: {voice_id})")
                char_context = "\nCharacters available:\n" + "\n".join(char_lines)

        # Build TTS constraints from channel config
        tts_context = ""
        if self._channel_config:
            tts_cfg = self._channel_config.get("tts", {})
            if tts_cfg:
                max_dur = tts_cfg.get("max_duration", "15")
                min_dur = tts_cfg.get("min_duration", "5")
                wps = tts_cfg.get("words_per_second", "2.5")
                tts_context = f"\nTTS constraints: max {max_dur}s, min {min_dur}s, ~{wps} words/sec"

        return f"""Generate {num_scenes} video scene scripts for Vietnamese content.

Title: {title}
Keywords: {kw_str}
Content angle: {angle}{char_context}{tts_context}

Return a JSON array of scenes. Each scene is an object with these exact fields:
- id: integer (1, 2, 3...)
- script: Vietnamese narration script (conversational, natural, WITH Vietnamese diacritics)
- background: short scene background description (5-15 words, e.g. "modern office workspace, bright colorful")
- characters: array of character name strings matching channel characters (e.g. ["Mentor"])

Structure:
- Scene 1 = HOOK: attention-grabbing opening, ask a question or make a bold statement
- Scene 2 to {num_scenes-1} = MAIN CONTENT: deliver key points with examples
- Scene {num_scenes} = CTA: call to action, ask to follow/like/share

Important:
- Write ALL scripts in Vietnamese WITH diacritics (e.g. "cải thiện", "quản lý thời gian")
- Do NOT mix English words like "time management" - use Vietnamese equivalents
- Use character names exactly as defined in the channel config
- Return ONLY the JSON array, no markdown, no explanation
"""

    def _parse_scenes(self, text: str) -> List[Dict]:
        """Parse JSON scenes from LLM response text."""
        try:
            scenes = json.loads(text)
            if isinstance(scenes, dict):
                scenes = scenes.get("scenes", [scenes])
            if isinstance(scenes, list) and scenes:
                return scenes
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return []

    def _fallback_scenes(self, title: str, keywords: List[str], angle: str,
                          num_scenes: int) -> List[Dict]:
        """Tiny fallback when LLM is unavailable — basic scene structure only."""
        kw = keywords[0] if keywords else "năng suất"
        hook = f"Bạn có muốn cải thiện {kw} không? Hãy cùng tôi khám phá những cách đơn giản nhưng hiệu quả!"

        scenes = [
            {
                "id": 1,
                "script": hook,
                "background": "modern office, bright colorful, Pixar Disney quality",
                "characters": ["GiaoVien"]
            },
            {
                "id": 2,
                "script": f"Phương pháp đầu tiên về {kw}: Hãy bắt đầu bằng việc lập kế hoạch cho ngày hôm nay. Viết ra những gì bạn muốn đạt được và theo dõi tiến độ. Đây là cách đơn giản nhưng cực kỳ hiệu quả.",
                "background": "person planning at desk, organized workspace, Pixar Disney quality",
                "characters": ["GiaoVien"]
            },
            {
                "id": 3,
                "script": f"Cuối cùng, hãy nhớ rằng cải thiện {kw} là một hành trình, không phải đích đến. Hãy kiên nhẫn với bản thân và tận hưởng quá trình! Theo dõi @NangSuatThongMinh để biết thêm nhiều mẹo hay!",
                "background": "motivated professional, sunrise, achievement concept, Pixar Disney quality",
                "characters": ["GiaoVien"]
            }
        ]
        return scenes[:num_scenes]

    def save_ideas_to_db(self, ideas: List[Dict], source_id: int = None) -> List[int]:
        """Save content ideas to DB, return list of idea IDs."""
        try:
            from db import save_content_ideas
            # Enrich ideas with project context
            for idea in ideas:
                idea["target_platform"] = idea.get("target_platform", self.target_platform)
            ids = save_content_ideas(self.project_id, ideas, source_id=source_id)
            logger.info(f"Saved {len(ids)} ideas to DB")
            return ids
        except Exception as e:
            logger.error(f"Failed to save ideas to DB: {e}")
            return []

    def update_idea_script(self, idea_id: int, script_json: Dict):
        """Update idea with generated script."""
        try:
            from db import update_idea_script as db_update_idea_script
            db_update_idea_script(idea_id, script_json)
            logger.info(f"Updated idea {idea_id} with script")
        except Exception as e:
            logger.error(f"Failed to update idea script: {e}")

    def get_ideas_by_status(self, status: str = "raw", limit: int = 10) -> List[Dict]:
        """Get content ideas by status."""
        try:
            from db import get_ideas_by_status
            return get_ideas_by_status(self.project_id, status, limit)
        except Exception as e:
            logger.error(f"Failed to get ideas: {e}")
            return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["productivity", "time management"]
    )

    test_idea = {
        "title": "3 Cách Quản Lý Thời Gian Hiệu Quả",
        "description": "Những phương pháp đơn giản giúp tăng năng suất",
        "topic_keywords": ["time management", "productivity", "efficiency"],
        "content_angle": "tips",
        "target_platform": "both"
    }

    print("Generating scene scripts from idea...")
    script = gen.generate_script_from_idea(test_idea, num_scenes=3)
    print(json.dumps(script, ensure_ascii=False, indent=2))
