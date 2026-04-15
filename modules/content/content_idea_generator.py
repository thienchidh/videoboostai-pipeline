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
from modules.pipeline.models import ChannelConfig, TechnicalConfig
from modules.pipeline.exceptions import ConfigMissingKeyError

logger = logging.getLogger(__name__)


class ContentIdeaGenerator:
    """Generate content ideas and video scripts from research topics.

    Uses LLM to generate scene scripts — no hardcoded templates.
    Swappable LLM backend via PluginRegistry (modules/llm/).
    """

    def __init__(self, project_id: int = None, target_platform: str = "both",
                 content_angle: str = "tips", niche_keywords: List[str] = None,
                 llm_config: Optional[Dict] = None,
                 channel_config: Optional[Dict] = None,
                 technical_config: TechnicalConfig = None):
        """
        Args:
            project_id: project ID for DB storage
            target_platform: 'facebook', 'tiktok', or 'both'
            content_angle: 'tips', 'educational', 'motivational', 'story'
            niche_keywords: list of niche keywords
            llm_config: Optional dict with 'provider', 'model', 'api_key' keys.
                         If None, resolves from config automatically.
            channel_config: Optional channel config dict. If provided, validated
                           via Pydantic ChannelConfig — missing required fields
                           raise ValidationError.
            technical_config: Optional TechnicalConfig for LLM settings.
                              If provided, reads generation.llm.* from it.
        """
        self.project_id = project_id
        self.target_platform = target_platform
        self.content_angle = content_angle
        self.niche_keywords = niche_keywords or []
        self._llm_config = llm_config or {}
        self._technical_config = technical_config

        # Read LLM settings from technical config (strict mode - raise if missing)
        if technical_config:
            model = technical_config.generation.llm.model
            if not model:
                raise ConfigMissingKeyError("generation.llm.model", "ContentIdeaGenerator")
            self._llm_config["model"] = model

            max_tokens = technical_config.generation.llm.max_tokens
            if max_tokens is None:
                raise ConfigMissingKeyError("generation.llm.max_tokens", "ContentIdeaGenerator")
            self._llm_config["max_tokens"] = max_tokens

            retry_attempts = technical_config.generation.llm.retry_attempts
            if retry_attempts is None:
                raise ConfigMissingKeyError("generation.llm.retry_attempts", "ContentIdeaGenerator")
            self._llm_config["retry_attempts"] = retry_attempts

            retry_backoff_max = technical_config.generation.llm.retry_backoff_max
            if retry_backoff_max is None:
                raise ConfigMissingKeyError("generation.llm.retry_backoff_max", "ContentIdeaGenerator")
            self._llm_config["retry_backoff_max"] = retry_backoff_max

        # Validate channel config with Pydantic — raise on missing required fields
        if channel_config:
            validated = ChannelConfig(**channel_config)
            self._channel_config = validated
        else:
            self._channel_config = None

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
        description = idea.get("description", "")  # actual article content from research

        scenes = self._generate_scenes(title, keywords, angle, description, num_scenes)

        # Read from validated ChannelConfig — no hardcoded fallbacks
        if not self._channel_config:
            raise ValueError("channel_config is required — pass a validated ChannelConfig")
        watermark = self._channel_config.watermark.text
        style = self._channel_config.style

        return {
            "title": title,
            "content_angle": angle,
            "keywords": keywords,
            "scenes": scenes,
            "watermark": watermark,
            "style": style,
            "generated_at": datetime.now().isoformat()
        }

    def _generate_scenes(self, title: str, keywords: List[str], angle: str,
                          description: str = "", num_scenes: int = 3) -> List[Dict]:
        """Generate scene scripts using LLM provider with exponential backoff retry.

        After initial generation, each scene's TTS is validated against channel
        duration bounds. Scenes that exceed bounds are regenerated (TTS text only)
        via _regenerate_scene_tts before being returned.
        """
        from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

        api_key = self._llm_config.get("api_key", "")
        if not api_key:
            # Read minimax key from technical config
            from modules.pipeline.models import TechnicalConfig
            api_key = TechnicalConfig.load().api_keys.minimax
            if not api_key:
                raise RuntimeError("minimax API key not found in config")

        llm = get_llm_provider(
            name=self._llm_config.get("provider", "minimax"),
            api_key=api_key,
            model=self._llm_config.get("model", "MiniMax-M2.7"),
        )
        prompt = self._build_scene_prompt(title, keywords, angle, description, num_scenes)

        @retry(
            stop=stop_after_attempt(self._llm_config.get("retry_attempts", 3)),
            wait=wait_exponential(multiplier=1, min=1, max=self._llm_config.get("retry_backoff_max", 10)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _call_llm():
            text = llm.chat(prompt, max_tokens=self._llm_config.get("max_tokens", 1536))
            scenes = self._parse_scenes(text)
            if not scenes:
                raise ValueError("Invalid scene format")
            return scenes

        scenes = _call_llm()
        logger.info(f"Generated {len(scenes)} scenes from LLM")

        # Validate each scene's TTS duration and regenerate if out of bounds
        if self._channel_config and self._channel_config.tts:
            tts_cfg = self._channel_config.tts
            wps = 2.5
            if self._technical_config and hasattr(self._technical_config, 'generation'):
                gen_cfg = self._technical_config.generation
                if hasattr(gen_cfg, 'tts') and gen_cfg.tts and hasattr(gen_cfg.tts, 'words_per_second'):
                    wps = gen_cfg.tts.words_per_second
                elif hasattr(gen_cfg, 'llm'):
                    pass  # keep wps=2.5 as default

            for scene in scenes:
                tts_text = scene.get("tts", "")
                if not tts_text:
                    continue
                if not self._validate_scene_duration(tts_text, tts_cfg, wps):
                    logger.warning(f"  ⚠️ Scene {scene.get('id', '?')} TTS out of bounds "
                                  f"({len(tts_text.split())} words), regenerating...")
                    regenerated = self._regenerate_scene_tts(
                        tts_text, tts_cfg, api_key=api_key, wps=wps
                    )
                    scene["tts"] = regenerated

        return scenes

    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             description: str = "", num_scenes: int = 3) -> str:
        """Build the prompt sent to LLM for scene generation."""
        if not self._channel_config:
            raise ValueError("channel_config is required")

        cfg = self._channel_config
        kw_list_str = ", ".join(keywords) if keywords else ""
        kw_line = f"Từ khóa: {kw_list_str}\n" if kw_list_str else ""
        all_char_names = [c.name for c in cfg.characters if c.name]
        char_list_str = ", ".join(all_char_names)

        tts = cfg.tts
        tts_context = f"\nGiới hạn thời lượng: tối đa {tts.max_duration}s, tối thiểu {tts.min_duration}s"

        # Build image style string from channel config for consistent art generation
        img_style = cfg.image_style
        if img_style:
            style_parts = [
                img_style.art_style or "",
                img_style.lighting or "",
                img_style.camera or "",
                img_style.environment or "",
                img_style.composition or "",
            ]
            art_style_str = ", ".join(p for p in style_parts if p)
        else:
            art_style_str = cfg.style or "3D render"

        desc_line = f"NỘI DUNG THAM KHẢO:\n{description[:1000]}\n" if description else ""

        return f"""Bạn là chuyên gia sản xuất video viral cho kênh "{cfg.name}".
Viết {num_scenes} scene giữ chân người xem từ giây đầu tiên.

Tiêu đề: {title}
{desc_line}{kw_line}Phong cách nội dung: {angle}{tts_context}

PHONG CÁCH HÌNH ẢNH CỦA KÊNH (CỐ ĐỊNH - KHÔNG ĐƯỢC THAY ĐỔI):
{art_style_str}

YÊU CẦU BẮT BUỘC:
- Lời thoại VIẾT TIẾNG VIỆT CÓ DẤU, tự nhiên như người nói thật
- KHÔNG dùng tiếng Anh - dùng tiếng Việt tương đương
- Chỉ chọn MỘT nhân vật duy nhất từ danh sách: [{char_list_str}] cho mỗi scene
- Background phải TUÂN THỦ tuyệt đối phong cách hình ảnh cố định ở trên - KHÔNG được tự ý thay đổi lighting, art_style, camera, environment hay composition

CẤU TRÚC SCENE:
- Scene 1 (MÓC HÓI): Mở đầu bằng statement táo bạo, câu hỏi gây sốc, hoặc số liệu bất ngờ. KHÔNG giới thiệu chủ đề — nhảy thẳng vào nội dung.
- Scene 2 đến Scene {num_scenes-1} (NỘI DUNG CHÍNH): Mỗi scene có 1 ý chính + ví dụ cụ thể, có thể kể chuyện hoặc dùng số liệu.
- Scene {num_scenes} (CTA): Không nói "like, follow, share" — hãy kể CTA như đang nói chuyện với viewer, ví dụ: "Bạn đã thử cách nào trong số này? Comment cho mình biết nhé!"

MỖI SCENE CẦN CÓ:
- id: số nguyên (1, 2, 3...)
- script: lời thoại tiếng Việt có dấu, mỗi scene 3-8 câu
- background: mô tả cảnh nền 5-15 từ, BẮT BUỘC chứa phong cách hình ảnh cố định [{art_style_str}] - ví dụ: "văn phòng hiện đại, {art_style_str}"
- character: tên MỘT nhân vật duy nhất được chọn từ [{char_list_str}]

Trả về CHỈ JSON array, không kèm markdown."""

    def _parse_scenes(self, text: str) -> List[Dict]:
        """Parse JSON scenes from LLM response text."""
        try:
            scenes = json.loads(text)
            if isinstance(scenes, dict):
                scenes = scenes.get("scenes", [scenes])
            if isinstance(scenes, list) and scenes:
                return self._validate_scenes(scenes)
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    return self._validate_scenes(json.loads(match.group()))
                except json.JSONDecodeError:
                    pass
        return []

    def _estimate_tts_duration(self, text: str, wps: float = 2.5) -> float:
        """Estimate TTS duration in seconds from text word count."""
        if not text or not text.strip():
            return 0.0
        word_count = len(text.split())
        return word_count / wps

    def _validate_scene_duration(self, scene_tts: str, tts_cfg,
                                  wps: float = 2.5) -> bool:
        """Return True if estimated TTS duration is within min/max bounds.

        Args:
            scene_tts: The TTS script text for one scene.
            tts_cfg: TTSConfig with min_duration and max_duration.
            wps: Words per second (from channel config, default 2.5).

        Returns:
            True if min_duration <= estimated_duration <= max_duration.
        """
        if not scene_tts or not scene_tts.strip():
            return True
        if tts_cfg is None:
            return True
        duration = self._estimate_tts_duration(scene_tts, wps)
        return tts_cfg.min_duration <= duration <= tts_cfg.max_duration

    def _regenerate_scene_tts(self, original_tts: str, tts_cfg,
                               api_key: str, wps: float = 2.5,
                               max_retries: int = 3) -> str:
        """Regenerate scene TTS text to fit duration bounds.

        Args:
            original_tts: The original TTS text that exceeded bounds.
            tts_cfg: TTSConfig with min_duration and max_duration.
            api_key: MiniMax API key for LLM calls.
            wps: Words per second for duration estimation.
            max_retries: Number of LLM retry attempts (default 3).

        Returns:
            New TTS text that fits bounds, or original_tts if all retries fail.
        """
        from modules.llm.minimax import MiniMaxLLMProvider

        target_duration = tts_cfg.max_duration * 0.9
        target_words = int(target_duration / wps)

        system_prompt = f"""Bạn là chuyên gia viết kịch bản TTS tiếng Việt ngắn gọn.
Nhiệm vụ: Viết lại kịch bản TTS cho một scene video.

YÊU CẦU:
- VIẾT TIẾNG VIỆT CÓ DẤU, tự nhiên như người nói thật
- Độ dài: CHÍNH XÁC khoảng {target_words} từ (tương đương {target_duration:.0f} giây TTS)
- KHÔNG thêm lời chào mở đầu như "Xin chào", "Hôm nay"
- KHÔNG thêm kết luận kiểu "Cảm ơn đã xem"
- Câu ngắn gọn, mỗi câu không quá 10 từ

Output: Chỉ output kịch bản TTS thuần túy, không có mở đầu hay kết thúc."""

        user_prompt = f"""Kịch bản gốc (hiện tại quá dài):
"{original_tts}"

Hãy viết lại kịch bản này để có độ dài phù hợp (khoảng {target_words} từ)."""

        for attempt in range(max_retries):
            try:
                llm = MiniMaxLLMProvider(api_key=api_key)
                new_tts = llm.chat(prompt=user_prompt, system=system_prompt, max_tokens=512)
                new_tts = new_tts.strip()
                if not new_tts:
                    logger.warning(f"  🤖 Regenerated TTS was empty (attempt {attempt+1}/{max_retries})")
                    continue
                if self._validate_scene_duration(new_tts, tts_cfg, wps):
                    logger.info(f"  🤖 Scene TTS regenerated ({attempt+1} attempt): "
                               f"{len(original_tts.split())} → {len(new_tts.split())} words")
                    return new_tts
                else:
                    logger.warning(f"  🤖 Regenerated TTS still out of bounds (attempt {attempt+1}/{max_retries})")
            except Exception as e:
                logger.warning(f"  🤖 LLM regeneration error: {e} (attempt {attempt+1}/{max_retries})")

        logger.warning(f"  ⚠️ All {max_retries} regeneration attempts failed — keeping original TTS")
        return original_tts

    def _validate_scenes(self, scenes: List[Dict]) -> List[Dict]:
        """Validate and normalize scene structure.

        Ensures each scene has:
        - character: str (not array)
        - 'characters' key removed if present
        - Falls back to first available character from config if missing.
        Always normalizes — channel_config only affects default character fallback.
        """
        # Determine default character from config if available
        if self._channel_config:
            available_chars = [c.name for c in self._channel_config.characters if c.name]
            default_char = available_chars[0] if available_chars else "Narrator"
        else:
            default_char = "Narrator"

        validated = []
        for scene in scenes:
            # Normalize: extract first from 'characters' array, or use 'character' string
            char = scene.get("character") or scene.get("characters")
            original_chars = char if isinstance(char, list) else None
            if isinstance(char, list):
                if len(char) > 1:
                    logger.warning(
                        f"Scene {scene.get('id', '?')} has {len(char)} characters "
                        f"({char}), expected 1. Using first: {char[0]}"
                    )
                char = char[0] if char else default_char
            elif not isinstance(char, str) or not char:
                char = default_char
            scene["character"] = char
            # Always remove 'characters' key — inconsistent field
            scene.pop("characters", None)
            validated.append(scene)

        return validated

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

    def update_idea_status(self, idea_id: int, status: str) -> bool:
        """Update status of a content idea."""
        from db import get_session, models
        with get_session() as session:
            idea = session.query(models.ContentIdea).filter_by(id=idea_id).first()
            if not idea:
                return False
            idea.status = status
            session.commit()
            return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Load channel config for testing
    from modules.pipeline.models import ChannelConfig
    channel_cfg = ChannelConfig.load("nang_suat_thong_minh")

    gen = ContentIdeaGenerator(
        project_id=1,
        content_angle="tips",
        niche_keywords=["productivity", "time management"],
        channel_config=channel_cfg,
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
