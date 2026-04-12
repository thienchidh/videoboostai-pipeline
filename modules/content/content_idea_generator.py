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
                 llm_config: Optional[Dict] = None):
        """
        Args:
            project_id: project ID for DB storage
            target_platform: 'facebook', 'tiktok', or 'both'
            content_angle: 'tips', 'educational', 'motivational', 'story'
            niche_keywords: list of niche keywords
            llm_config: Optional dict with 'provider', 'model', 'api_key' keys.
                         If None, resolves from config automatically.
        """
        self.project_id = project_id
        self.target_platform = target_platform
        self.content_angle = content_angle
        self.niche_keywords = niche_keywords or ["productivity", "time management", "năng suất"]
        self._llm_config = llm_config or {}

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
        """Generate scene scripts using LLM provider (or tiny fallback)."""
        try:
            llm = get_llm_provider(
                name=self._llm_config.get("provider", "minimax"),
                api_key=self._llm_config.get("api_key", ""),
                model=self._llm_config.get("model", "MiniMax-M2.7"),
            )
            prompt = self._build_scene_prompt(title, keywords, angle, num_scenes)
            text = llm.chat(prompt, max_tokens=1536)
            scenes = self._parse_scenes(text)
            if scenes:
                return scenes
        except Exception as e:
            logger.warning(f"LLM scene generation failed: {e}")

        return self._fallback_scenes(title, keywords, angle, num_scenes)

    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             num_scenes: int) -> str:
        """Build the prompt sent to LLM for scene generation."""
        kw_str = ", ".join(keywords) if keywords else "productivity, time management"
        return f"""Generate {num_scenes} video scene scripts for Vietnamese content.

Title: {title}
Keywords: {kw_str}
Content angle: {angle}

Return a JSON array of scenes. Each scene is an object with these exact fields:
- id: integer (1, 2, 3...)
- script: Vietnamese narration script (50-100 words per scene, conversational, natural)
- background: short scene background description (5-15 words, e.g. "modern office workspace, bright colorful")
- characters: array of character name strings (e.g. ["GiaoVien"])

Structure:
- Scene 1 = HOOK: attention-grabbing opening, ask a question or make a bold statement (~15s)
- Scene 2 to {num_scenes-1} = MAIN CONTENT: deliver key points with examples (~20-30s each)
- Scene {num_scenes} = CTA: call to action, ask to follow/like/share (~10s)

Important:
- Write ALL scripts in Vietnamese
- Each script must be 50-100 words
- Background descriptions should evoke the scene setting for image generation
- Use natural conversational Vietnamese, not formal writing
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
        idea_ids = []
        try:
            from psycopg2.extras import Json
            from db import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    for idea in ideas:
                        cur.execute(
                            """INSERT INTO content_ideas
                               (project_id, title, description, topic_keywords, content_angle,
                                target_platform, source_id, status)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, 'raw')
                               RETURNING id""",
                            (
                                self.project_id,
                                idea.get("title"),
                                idea.get("description"),
                                Json(idea.get("topic_keywords", [])),
                                idea.get("content_angle"),
                                idea.get("target_platform", "both"),
                                source_id
                            )
                        )
                        idea_ids.append(cur.fetchone()["id"])
                    logger.info(f"Saved {len(idea_ids)} ideas to DB")
        except Exception as e:
            logger.error(f"Failed to save ideas to DB: {e}")
        return idea_ids

    def update_idea_script(self, idea_id: int, script_json: Dict):
        """Update idea with generated script."""
        try:
            from psycopg2.extras import Json
            from db import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE content_ideas
                           SET script_json = %s, status = 'script_ready', updated_at = CURRENT_TIMESTAMP
                           WHERE id = %s""",
                        (Json(script_json), idea_id)
                    )
                    logger.info(f"Updated idea {idea_id} with script")
        except Exception as e:
            logger.error(f"Failed to update idea script: {e}")

    def get_ideas_by_status(self, status: str = "raw", limit: int = 10) -> List[Dict]:
        """Get content ideas by status."""
        try:
            from psycopg2.extras import RealDictCursor
            from db import get_db
            with get_db() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """SELECT * FROM content_ideas
                           WHERE project_id = %s AND status = %s
                           ORDER BY created_at DESC LIMIT %s""",
                        (self.project_id, status, limit)
                    )
                    return cur.fetchall()
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
