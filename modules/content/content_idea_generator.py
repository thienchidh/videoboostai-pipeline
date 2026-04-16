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
from modules.pipeline.models import ChannelConfig, TechnicalConfig, SceneConfig
from modules.pipeline.exceptions import ConfigMissingKeyError

logger = logging.getLogger(__name__)


class ContentIdeaGenerator:
    """Generate content ideas and video scripts from research topics.

    Uses LLM to generate scene scripts — no hardcoded templates.
    Swappable LLM backend via PluginRegistry (modules/llm/).
    """

    def __init__(self, project_id: int = None, target_platform: str = "both",
                 content_angle: str = "tips", niche_keywords: List[str] = None,
                 llm_config: Optional["GenerationLLM"] = None,
                 channel_config: Optional[ChannelConfig] = None,
                 technical_config: TechnicalConfig = None):
        """
        Args:
            project_id: project ID for DB storage
            target_platform: 'facebook', 'tiktok', or 'both'
            content_angle: 'tips', 'educational', 'motivational', 'story'
            niche_keywords: list of niche keywords
            llm_config: GenerationLLM Pydantic model. If provided, used directly.
                        If not, reads from technical_config.generation.llm.
            channel_config: ChannelConfig Pydantic model. Required for script generation.
            technical_config: TechnicalConfig Pydantic model. Used to resolve api_key
                              if llm_config is not provided.
        """
        from modules.pipeline.models import GenerationLLM

        self.project_id = project_id
        self.target_platform = target_platform
        self.content_angle = content_angle
        self.niche_keywords = niche_keywords or []

        # Resolve llm_config: prefer explicit param, fall back to technical_config
        if llm_config is not None:
            if not isinstance(llm_config, GenerationLLM):
                raise TypeError(f"llm_config must be a GenerationLLM Pydantic model, got {type(llm_config).__name__}")
            self._llm = llm_config
        elif technical_config is not None:
            self._llm = technical_config.generation.llm
        else:
            # Neither provided — defer to per-scene TechnicalConfig.load() (lazy)
            self._llm = None

        # Store channel config (already validated by caller)
        self._channel_config = channel_config
        self._technical_config = technical_config

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

        from modules.pipeline.models import TechnicalConfig

        # Resolve api_key — from technical_config if not provided via GenerationLLM (it doesn't have api_key)
        if not self._llm or not self._llm.model:
            raise ConfigMissingKeyError("generation.llm.model", "ContentIdeaGenerator")
        tech_cfg = self._technical_config if self._technical_config else TechnicalConfig.load()
        api_key = tech_cfg.api_keys.minimax
        if not api_key:
            raise RuntimeError("minimax API key not found in config")

        llm = get_llm_provider(
            name=self._llm.provider if self._llm else "minimax",
            api_key=api_key,
            model=self._llm.model if self._llm else "MiniMax-M2.7",
        )
        prompt = self._build_scene_prompt(title, keywords, angle, description, num_scenes)

        @retry(
            stop=stop_after_attempt(self._llm.retry_attempts if self._llm else 3),
            wait=wait_exponential(multiplier=1, min=1, max=self._llm.retry_backoff_max if self._llm else 10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _call_llm():
            text = llm.chat(prompt, max_tokens=self._llm.max_tokens if self._llm else 1536)
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
            if self._technical_config and self._technical_config.generation:
                gen_cfg = self._technical_config.generation
                if gen_cfg.tts:
                    wps = gen_cfg.tts.words_per_second

            for scene in scenes:
                tts_text = scene.tts or ""
                if not tts_text:
                    continue
                if not self._validate_scene_duration(tts_text, tts_cfg, wps):
                    logger.warning(f"  ⚠️ Scene {scene.id or 0} TTS out of bounds "
                                  f"({len(tts_text.split())} words), regenerating...")
                    regenerated = self._regenerate_scene_tts(
                        tts_text, tts_cfg, api_key=api_key, wps=wps
                    )
                    scene.tts = regenerated

        return scenes

    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             description: str = "", num_scenes: int = 3) -> str:
        """Build the prompt sent to LLM for scene generation.

        Uses Two-Phase Creative Generation:
        Phase 1: LLM creates creative_brief for each scene (vision/plan)
        Phase 2: LLM writes image_prompt and lipsync_prompt from creative_brief

        Includes few-shot examples, anti-patterns, and diversity constraints
        to ensure variety across scenes.
        """
        if not self._channel_config:
            raise ValueError("channel_config is required")

        cfg = self._channel_config
        kw_list_str = ", ".join(keywords) if keywords else ""
        kw_line = f"Từ khóa: {kw_list_str}\n" if kw_list_str else ""

        # Build character list with voice context for LLM
        char_lines = []
        for c in cfg.characters:
            voice_info = getattr(c, 'voice_id', '') or ""
            char_lines.append(f"- {c.name}: {voice_info}")
        char_list_str = "\n".join(char_lines)

        tts = cfg.tts
        tts_context = (
            f"\nGiới hạn thời lượng: tối đa {tts.max_duration}s, tối thiểu {tts.min_duration}s mỗi scene. "
            f"Mỗi scene phải có khoảng {int(tts.min_duration * 2.5)}-{int(tts.max_duration * 2.5)} từ "
            f"(với tốc độ 2.5 từ/giây)."
        )

        desc_line = f"NỘI DUNG THAM KHẢO:\n{description[:1000]}\n" if description else ""

        return f"""Bạn là chuyên gia sản xuất video viral cho kênh "{cfg.name}".
Viết {num_scenes} scene với prompts SÁNG TẠO, KHÔNG LẶP LẠI.

{desc_line}{kw_line}Phong cách nội dung: {angle}{tts_context}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}

NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str}

TRƯỚC TIÊN: Dựa trên title, keywords và content_angle, xác định "video_message" — thông điệp chính mà người xem sẽ MANG GÌ ĐI sau khi xem video này. Message phải NGẮN GỌN (1-2 câu), CÓ Ý NGHĨA RÕ RÀNG.

SAU ĐÓ: Viết {num_scenes} scenes, mỗi scene phải:
- Cùng hướng về video_message đã xác định ở trên
- Nội dung mỗi scene phải SUPPORT hoặc ILLUSTRATE cái message đó
- Khác nhau về visual concept, emotion, camera angle, setting
- KHÔNG được viết scene mà content không liên quan đến video_message

---

VÍ DỤ TỐT (học cách viết creative brief + prompts):

Input topic: "3 Tips Quản Lý Thời Gian"
Characters: NamMinh (female, vi-VN-NamMinhNeural), HoaiMy (female, vi-VN-HoaiMyNeural)

--- Scene 1 (Tip về lập kế hoạch) ---
creative_brief:
  visual_concept: "Close-up khuôn mặt tập trung, ánh sáng warm từ lamp"
  emotion: "serious but approachable"
  camera_mood: "shallow DOF, intimate close-up"
  setting_vibe: "home office with plants"
  unique_angle: "shooting from above desk, papers and planner visible"
  action_description: "speaking directly to camera, occasional hand gesture toward planner"

image_prompt: "Close-up of a focused young woman at a desk with planner and scattered papers, warm lamp light creating soft shadows, shallow depth of field with desk details in bokeh, home office with small plants, looking directly at camera with determined yet approachable expression, intimate cinematic feel, professional 3D render style"

lipsync_prompt: "NamMinh speaking directly to camera with warm inviting smile, slight nod on key words like 'planning' and 'important', occasional hand gesture toward planner, measured thoughtful pace, confident energy, Vietnamese language delivery"

--- Scene 2 (Tip về ưu tiên) ---
creative_brief:
  visual_concept: "Medium shot người đang cầm list, ánh sáng bright white"
  emotion: "energetic, motivated"
  camera_mood: "medium shot, eye-level, slightly high angle"
  setting_vibe: "clean minimalist workspace"
  unique_angle: "camera to the side, showing screen with task list"
  action_description: "pointing at list, engaging body language"

image_prompt: "Young professional woman pointing at a digital task list on screen, clean minimalist white workspace, bright diffused lighting from ceiling, medium shot eye-level with slightly high angle, engaged and energetic expression, professional 3D render style"

lipsync_prompt: "HoaiMy speaking with energetic enthusiasm, animated hand gestures pointing at list items, faster paced delivery with excitement on priority keywords, confident authoritative tone, Vietnamese language delivery"

--- Scene 3 (Tip về nghỉ ngơi) ---
creative_brief:
  visual_concept: "Relaxed shot người đang uống coffee, ánh sáng soft golden"
  emotion: "relaxed, balanced"
  camera_mood: "wide shot, lifestyle feel"
  setting_vibe: "cozy café corner with plants"
  unique_angle: "over-the-shoulder showing coffee cup"
  action_description: "relaxed posture, occasional sip, thoughtful pauses"

image_prompt: "Young woman relaxing with coffee cup, soft golden hour lighting from window, cozy café corner with plants and warm wooden elements, over-the-shoulder composition showing both face and coffee, relaxed balanced expression with slight smile, lifestyle photography feel, professional 3D render style"

lipsync_prompt: "NamMinh speaking in a relaxed slower pace, occasional sip of coffee between sentences, thoughtful pauses on key points, warm casual tone, gentle hand movements, peaceful balanced energy, Vietnamese language delivery"

---

TRÁNH CÁC PATTERN SAU — KHÔNG ĐƯỢC LẶP LẠI:
❌ "professional speaker in modern office" — DÙNG QUÁ NHIỀU, XÓA
❌ "warm lighting, eye-level camera" — QUÁ GENERIC, KHÔNG MÔ TẢ GÌ
❌ Mọi scene đều là người đứng nói chuyện trước camera
❌ Mọi scene đều có cùng background (office)
❌ "confident, knowledgeable" — adjectives TRỐNG, không có action
❌ "gesturing naturally" — quá mơ hồ
❌ Tất cả scenes đều có cùng camera angle (close-up)
❌ Prompt bắt đầu bằng "A person..." thay vì mô tả cụ thể

---

MỖI SCENE PHẢI KHÁC NHAU — CAM KẾT TRƯỚC:
1. Scene N+1 phải có ÍT NHẤT 1 trong:
   - Camera angle khác (close-up ≠ medium ≠ wide)
   - Emotion khác (serious ≠ playful ≠ calm)
   - Setting khác (office ≠ café ≠ outdoor)

2. Không được dùng cùng lighting setup cho 2 scene liên tiếp
   (warm lamp → bright white → golden hour → soft blue)

3. Mỗi scene phải có "unique visual element" — detail nhỏ đặc biệt
   VD: "có sách stack trên bàn", "cây cảnh trong góc", "light leak từ cửa sổ"

4. Nếu script có emotion mạnh (excited, serious, funny) →
   camera_mood phải phản ánh đúng emotion đó

---

ĐỊNH DẠNG JSON OUTPUT:
{{
  "video_message": "thông điệp chính mà người xem MANG ĐI sau khi xem xong video — NGẮN GỌN (1-2 câu), CÓ Ý NGHĨA RÕ RÀNG. Tất cả scenes phải SUPPORT hoặc ILLUSTRATE thông điệp này.",
  "scenes": [
    {{
      "id": 1,
      "script": "lời thoại TTS...",
      "character": "NamMinh",
      "creative_brief": {{
        "visual_concept": "mô tả ngắn gọn concept visual",
        "emotion": "mood chính của scene",
        "camera_mood": "camera angle + depth of field",
        "setting_vibe": "mô tả không gian/background",
        "unique_angle": "detail đặc biệt chỉ có scene này",
        "action_description": "mô tả body language, gesture"
      }},
      "image_prompt": "PROMPT HOÀN CHỈNH cho image gen, CHỨÁ creative_brief elements",
      "lipsync_prompt": "PROMPT HOÀN CHỈNH cho lipsync, CHỨÁ emotion + action + pace"
    }}
  ]
}}

Trả về CHỈ JSON object có video_message và scenes, không kèm markdown."""

    def _parse_scenes(self, text: str) -> List[SceneConfig]:
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

    def _validate_scenes(self, scenes: List[Dict]) -> List[SceneConfig]:
        """Validate and normalize scene structure.

        Ensures each scene has:
        - character: str (not array)
        - 'characters' key removed if present
        - Falls back to first available character from config if missing.
        - image_prompt and lipsync_prompt are None (not missing) if absent.
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
                        f"Scene {scene.get('id', 0)} has {len(char)} characters "
                        f"({char}), expected 1. Using first: {char[0]}"
                    )
                char = char[0] if char else default_char
            elif not isinstance(char, str) or not char:
                char = default_char
            scene["character"] = char
            # Always remove 'characters' key — inconsistent field
            scene.pop("characters", None)
            # Normalize: ensure image_prompt and lipsync_prompt are present (or None)
            scene["image_prompt"] = scene.get("image_prompt") or None
            scene["lipsync_prompt"] = scene.get("lipsync_prompt") or None
            scene["creative_brief"] = scene.get("creative_brief") or None
            validated.append(scene)

        return [SceneConfig.from_dict(s) for s in validated]

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
