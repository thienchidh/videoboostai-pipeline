#!/usr/bin/env python3
"""
content_idea_generator.py - Generate content ideas and video scripts from topics
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


# Content templates for video scenes
CONTENT_TEMPLATES = {
    "tips": {
        "hook_pattern": "Bạn có biết ...? Đây là {} để ...!",
        "structure": ["hook", "tip_1", "tip_2", "tip_3", "cta"],
        "scene_template": [
            {"type": "hook", "duration_est": "~15s"},
            {"type": "tip", "duration_est": "~20s"},
            {"type": "tip", "duration_est": "~20s"},
            {"type": "cta", "duration_est": "~10s"}
        ]
    },
    "educational": {
        "hook_pattern": "Bạn có biết tại sao ...? Hôm nay chúng ta sẽ tìm hiểu về ...",
        "structure": ["hook", "explain", "example", "summary", "cta"],
        "scene_template": [
            {"type": "hook", "duration_est": "~15s"},
            {"type": "main", "duration_est": "~40s"},
            {"type": "summary", "duration_est": "~10s"},
            {"type": "cta", "duration_est": "~10s"}
        ]
    },
    "motivational": {
        "hook_pattern": "Hãy dừng lại và suy nghĩ về ...",
        "structure": ["story", "lesson", "action", "cta"],
        "scene_template": [
            {"type": "story", "duration_est": "~25s"},
            {"type": "lesson", "duration_est": "~20s"},
            {"type": "action", "duration_est": "~10s"},
            {"type": "cta", "duration_est": "~10s"}
        ]
    },
    "story": {
        "hook_pattern": "Câu chuyện hôm nay về một người đã thay đổi ...",
        "structure": ["intro", "story_body", "lesson", "cta"],
        "scene_template": [
            {"type": "intro", "duration_est": "~15s"},
            {"type": "story", "duration_est": "~35s"},
            {"type": "lesson", "duration_est": "~15s"},
            {"type": "cta", "duration_est": "~10s"}
        ]
    }
}


class ContentIdeaGenerator:
    """Generate content ideas and video scripts from research topics."""

    def __init__(self, project_id: int = None, target_platform: str = "both",
                 content_angle: str = "tips", niche_keywords: List[str] = None):
        """
        Args:
            project_id: project ID for DB storage
            target_platform: 'facebook', 'tiktok', or 'both'
            content_angle: 'tips', 'educational', 'motivational', 'story'
            niche_keywords: list of niche keywords
        """
        self.project_id = project_id
        self.target_platform = target_platform
        self.content_angle = content_angle
        self.niche_keywords = niche_keywords or ["productivity", "time management", "năng suất"]
        self.template = CONTENT_TEMPLATES.get(content_angle, CONTENT_TEMPLATES["tips"])

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
        angle = idea.get("content_angle", "tips")
        template = CONTENT_TEMPLATES.get(angle, CONTENT_TEMPLATES["tips"])

        # Generate scene scripts
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
        """Generate scene scripts using LLM or template fallback."""

        if OLLAMA_AVAILABLE:
            try:
                return self._llm_generate_scenes(title, keywords, angle, num_scenes)
            except Exception as e:
                logger.warning(f"LLM failed: {e}, using template fallback")

        return self._template_generate_scenes(title, keywords, angle, num_scenes)

    def _llm_generate_scenes(self, title: str, keywords: List[str], angle: str,
                             num_scenes: int) -> List[Dict]:
        """Use LLM to generate scene scripts."""
        prompt = f"""Generate {num_scenes} scene scripts for a Vietnamese video about: {title}

Keywords: {', '.join(keywords)}
Content angle: {angle}

For each scene provide:
- id: scene number (1, 2, 3...)
- script: Vietnamese narration script (50-100 words per scene)
- background: scene background description
- characters: ["GiaoVien"]

Return as JSON array with these exact fields.
Scene 1 is HOOK (attention-grabbing opening).
Scene 2 and 3 provide main content.
"""

        response = ollama.chat(
            model='llama3.2',
            messages=[{'role': 'user', 'content': prompt}]
        )

        content = response['message']['content']
        try:
            scenes = json.loads(content)
            if isinstance(scenes, dict):
                scenes = scenes.get('scenes', [scenes])
            return scenes
        except:
            import re
            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                return json.loads(match.group())
            return self._template_generate_scenes(title, keywords, angle, num_scenes)

    def _template_generate_scenes(self, title: str, keywords: List[str], angle: str,
                                  num_scenes: int) -> List[Dict]:
        """Generate scene scripts from templates (fallback when LLM unavailable)."""

        if angle == "tips":
            scene_templates = [
                {
                    "id": 1,
                    "script": f"Bạn có bao giờ cảm thấy {keywords[0] if keywords else 'công việc'} khiến bạn quá tải không? Đây là những mẹo giúp bạn cải thiện ngay hôm nay!",
                    "background": "modern office, bright colorful, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                },
                {
                    "id": 2,
                    "script": f"Mẹo số một về {keywords[0] if keywords else 'quản lý thời gian'}: Hãy bắt đầu bằng việc ưu tiên những công việc quan trọng nhất trước. Đừng để những việc nhỏ lấy đi thời gian của bạn. {}.".format(
                        "Áp dụng nguyên tắc 80/20: 20% công việc tạo ra 80% kết quả" if keywords else ""
                    ),
                    "background": "modern office workspace, focused professional, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                },
                {
                    "id": 3,
                    "script": f"Mẹo cuối cùng: {keywords[1] if len(keywords) > 1 else 'Hãy kiên trì và theo dõi tiến độ'} mỗi ngày. Chỉ cần 15-30 phút để lập kế hoạch, bạn sẽ tiết kiệm được cả giờ làm việc hiệu quả hơn. {}.".format(
                        "Đây là cách những người thành công bắt đầu mỗi ngày của họ!" if keywords else ""
                    ),
                    "background": "cozy productive workspace, morning light, organized desk, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                }
            ]
        elif angle == "educational":
            scene_templates = [
                {
                    "id": 1,
                    "script": f"Chào mừng bạn đến với chủ đề hôm nay: {title}. Hãy cùng tôi khám phá những điều quan trọng về {keywords[0] if keywords else 'năng suất làm việc'}!",
                    "background": "modern classroom, bright colors, animated graphics, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                },
                {
                    "id": 2,
                    "script": f"Điểm mấu chốt về {keywords[0] if keywords else 'quản lý thời gian'} là hiểu rằng: chúng ta không thể có thêm thời gian, nhưng chúng ta có thể quản lý nó tốt hơn. {}.".format(
                        "Hãy áp dụng những phương pháp đã được chứng minh khoa học." if keywords else ""
                    ),
                    "background": "animated educational graphics, time concept visual, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                },
                {
                    "id": 3,
                    "script": f"Tóm lại, để cải thiện {keywords[0] if keywords else 'năng suất'}, hãy nhớ: ưu tiên công việc quan trọng, loại bỏ yếu tố gây phân tâm, và theo dõi tiến độ mỗi ngày. {}.".format(
                        "Hãy theo dõi để biết thêm nhiều mẹo tiếp theo!" if keywords else ""
                    ),
                    "background": "modern office, motivated professional, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                }
            ]
        else:
            # Default template
            scene_templates = [
                {
                    "id": 1,
                    "script": f"Bạn có muốn cải thiện {keywords[0] if keywords else 'năng suất làm việc'} của mình không? Hãy cùng tôi khám phá những cách đơn giản nhưng hiệu quả!",
                    "background": "modern office, bright colorful, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                },
                {
                    "id": 2,
                    "script": f"Phương pháp đầu tiên: {keywords[0] if keywords else 'Hãy bắt đầu bằng việc lập kế hoạch cho ngày hôm nay'}. Viết ra những gì bạn muốn đạt được và theo dõi tiến độ. Đây là cách đơn giản nhưng cực kỳ hiệu quả.",
                    "background": "person planning at desk, organized workspace, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                },
                {
                    "id": 3,
                    "script": f"Cuối cùng, hãy nhớ rằng: {} cải thiện {keywords[0] if keywords else 'năng suất'} là một hành trình, không phải đích đến. Hãy kiên nhẫn với bản thân và tận hưởng quá trình! Theo dõi @NangSuatThongMinh để biết thêm nhiều mẹo hay!".format(
                        "sự" if keywords else ""
                    ),
                    "background": "motivated professional, sunrise, achievement concept, Pixar Disney quality",
                    "characters": ["GiaoVien"]
                }
            ]

        return scene_templates[:num_scenes]

    def save_ideas_to_db(self, ideas: List[Dict], source_id: int = None) -> List[int]:
        """Save content ideas to DB, return list of idea IDs."""
        idea_ids = []
        try:
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
            from db import get_db
            from psycopg2.extras import RealDictCursor
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
        niche_keywords=["productivity", "time management", "năng suất"]
    )

    # Test template generation
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
