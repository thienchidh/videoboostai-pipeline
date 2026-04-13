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
        """Generate scene scripts using LLM provider with retry on parse failure."""
        api_key = self._llm_config.get("api_key", "") if self._llm_config else ""
        if not api_key:
            # Read minimax key from technical config
            import yaml
            from core.paths import PROJECT_ROOT
            tech_cfg_path = PROJECT_ROOT / "configs" / "technical" / "config_technical.yaml"
            with open(tech_cfg_path, encoding="utf-8") as f:
                tech_cfg = yaml.safe_load(f)
            api_key = tech_cfg.get("api", {}).get("keys", {}).get("minimax", "")
            if not api_key:
                raise RuntimeError("minimax API key not found in config")

        llm = get_llm_provider(
            name=self._llm_config.get("provider", "minimax") if self._llm_config else "minimax",
            api_key=api_key,
            model=self._llm_config.get("model", "MiniMax-M2.7") if self._llm_config else "MiniMax-M2.7",
        )
        prompt = self._build_scene_prompt(title, keywords, angle, num_scenes)

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                text = llm.chat(prompt, max_tokens=1536)
                scenes = self._parse_scenes(text)
                if scenes:
                    logger.info(f"Generated {len(scenes)} scenes from LLM (attempt {attempt + 1})")
                    return scenes
                logger.warning(f"LLM returned invalid format (attempt {attempt + 1}/{max_retries + 1})")
            except Exception as e:
                logger.warning(f"LLM call failed: {e} (attempt {attempt + 1}/{max_retries + 1})")

        raise RuntimeError(f"LLM failed after {max_retries + 1} attempts for: {title[:30]}")

    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             num_scenes: int) -> str:
        """Build the prompt sent to LLM for scene generation."""
        kw_str = ", ".join(keywords) if keywords else "năng suất, quản lý thời gian"

        # Build character context from channel config (single char only)
        char_name = "Mentor"
        if self._channel_config:
            chars = self._channel_config.get("characters", [])
            if chars:
                char_name = chars[0].get("name", "Mentor")

        # Build TTS constraints from channel config
        tts_context = ""
        if self._channel_config:
            tts_cfg = self._channel_config.get("tts", {})
            if tts_cfg:
                max_dur = tts_cfg.get("max_duration", 15)
                min_dur = tts_cfg.get("min_duration", 5)
                wps = tts_cfg.get("words_per_second", 2.5)
                tts_context = f"\nRàng buộc TTS: tối đa {max_dur}s, tối thiểu {min_dur}s, ~{wps} từ/giây"

        return f"""Bạn là một chuyên gia sản xuất video TikTok/Facebook cho kênh "Năng Suất Thông Minh".
Hãy tạo {num_scenes} kịch bản scene cho video với chủ đề:

Tiêu đề: {title}
Từ khóa: {kw_str}
Phong cách: {angle}{tts_context}

YÊU CẦU:
- Tất cả lời thoại phải VIẾT TIẾNG VIỆT CÓ DẤU (ví dụ: "cải thiện", "quản lý thời gian", "năng suất làm việc")
- KHÔNG dùng tiếng Anh như "time management" - phải dùng tiếng Việt tương đương
- Viết lời thoại tự nhiên, gần gũi như đang nói chuyện với khán giả
- Nhân vật duy nhất: "{char_name}"

CẤU TRÚC SCENE:
- Scene 1 = MÓC HÓI: câu hỏi gây tò mò hoặc statement táo bạo
- Scene 2 đến Scene {num_scenes-1} = NỘI DUNG CHÍNH: trình bày ý chính có ví dụ minh họa
- Scene {num_scenes} = CTA: kêu gọi hành động (like, follow, share)

MỖI SCENE CẦN CÓ:
- id: số nguyên (1, 2, 3...)
- script: lời thoại tiếng Việt có dấu, tự nhiên như người nói thật
- background: mô tả cảnh nền ngắn 5-15 từ (ví dụ: "văn phòng hiện đại, ánh sáng ấm, 3D render")
- characters: mảng tên nhân vật - luôn dùng ["{char_name}"]

Trả về CHỈ JSON array, không kèm markdown, không giải thích thêm."""

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
