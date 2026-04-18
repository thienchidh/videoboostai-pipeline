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
from typing import Dict, List, Optional, Tuple

from modules.llm import get_llm_provider
from modules.pipeline.models import ChannelConfig, TechnicalConfig, SceneConfig, ScriptOutput
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

    def generate_script_from_idea(self, idea: Dict, num_scenes: int = 3) -> ScriptOutput:
        """
        Generate scene scripts from a content idea.
        Returns ScriptOutput Pydantic model (not Dict) for direct attribute access.
        """
        title = idea.get("title", "")
        keywords = idea.get("topic_keywords", [])
        angle = idea.get("content_angle", self.content_angle)
        description = idea.get("description", "")  # actual article content from research

        # Step 1: generate video_message (never null)
        video_message = self._generate_video_message(title, keywords, angle, description)
        # Step 2: generate scenes using video_message as mandatory context
        scenes, _ = self._generate_scenes(title, keywords, angle, description, num_scenes, video_message)

        # Read from validated ChannelConfig — no hardcoded fallbacks
        if not self._channel_config:
            raise ValueError("channel_config is required — pass a validated ChannelConfig")
        watermark = self._channel_config.watermark.text
        style = self._channel_config.style

        return ScriptOutput(
            title=title,
            content_angle=angle,
            keywords=keywords,
            scenes=scenes,  # List[SceneConfig] - direct Pydantic objects
            video_message=video_message,
            watermark=watermark,
            style=style,
            generated_at=datetime.now().isoformat()
        )

    def _generate_scenes(self, title: str, keywords: List[str], angle: str,
                          description: str, num_scenes: int,
                          video_message: str) -> Tuple[List[SceneConfig], Optional[str]]:
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
        prompt = self._build_scene_prompt(title, keywords, angle, description, num_scenes, video_message)

        @retry(
            stop=stop_after_attempt(self._llm.retry_attempts if self._llm else 3),
            wait=wait_exponential(multiplier=1, min=1, max=self._llm.retry_backoff_max if self._llm else 10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _call_llm():
            raw_text = llm.chat(prompt, max_tokens=8192)
            video_message = self._extract_video_message(raw_text)
            scenes = self._parse_scenes(raw_text)
            if not scenes:
                logger.warning(f"  LLM returned invalid scene format. Raw response (first 500 chars): {raw_text[:500]}")
                raise ValueError("Invalid scene format")
            return scenes, video_message

        scenes, video_message = _call_llm()
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

        return scenes, video_message

    def _build_scene_prompt(self, title: str, keywords: List[str], angle: str,
                             description: str, num_scenes: int,
                             video_message: str) -> str:
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
            voice_info = c.voice_id or ""
            char_lines.append(f"- {c.name}: {voice_info}")
        char_list_str = "\n".join(char_lines)

        tts = cfg.tts
        tts_context = (
            f"\nGiới hạn thời lượng: tối đa {tts.max_duration}s, tối thiểu {tts.min_duration}s mỗi scene. "
            f"Mỗi scene phải có khoảng {int(tts.min_duration * 2.5)}-{int(tts.max_duration * 2.5)} từ "
            f"(với tốc độ 2.5 từ/giây)."
        )

        desc_line = f"NỘI DUNG THAM KHẢO:\n{description[:1000]}\n" if description else ""

        # Build image style constraints string
        img_style = cfg.image_style
        if img_style:
            img_style_str = (f"- lighting: {img_style.lighting}\n"
                             f"- camera: {img_style.camera}\n"
                             f"- art_style: {img_style.art_style}\n"
                             f"- environment: {img_style.environment}\n"
                             f"- composition: {img_style.composition}")
        else:
            img_style_str = "(không có constraints cụ thể)"

        return f"""Bạn là chuyên gia sản xuất video viral cho kênh "{cfg.name}".
Viết {num_scenes} scene với prompts SÁNG TẠO, KHÔNG LẶP LẠI.

{desc_line}{kw_line}Phong cách nội dung: {angle}{tts_context}

PHONG CÁCH KÊNH (brand tone):
{cfg.style}

IMAGE STYLE CONSTRAINTS (phải include trong image_prompt):
{img_style_str}

NHÂN VẬT VÀ GIỌNG NÓI:
{char_list_str}

VIDEO_MESSAGE (BẮT BUỘC PHẢI ILLUSTRATE/SUPPORT):
"{video_message}"
→ Tất cả scenes phải giúp viewer hiểu HOẶC tin video_message này
→ Không viết scene nào không liên quan đến video_message

NỘI DUNG THAM KHẢO:
{desc_line}{kw_line}Phong cách: {angle}

PHONG CÁCH KÊNH:
{cfg.style}

NHÂN VẬT:
{char_list_str}

GIỚI HẠN: mỗi scene {int(tts.min_duration)}-{int(tts.max_duration)} giây ({int(tts.min_duration*2.5)}-{int(tts.max_duration*2.5)} từ)

---

CẤU TRÚC SCENES:

1. Scene 1 — HOOK: Câu hỏi HOẶC provocative statement. PHẢI có hint/trả lời một phần.
   ✅ "Olympic không dùng Pomodoro — họ dùng gì? Và HIỆU QUẢ HƠN 40%"
   ❌ "Bạn có biết bí mật năng suất của Olympic không?"

2. Scene 2+ — INSIGHT / TECHNIQUE / PROOF: Mỗi scene phải deliver:
   - FACT: số liệu cụ thể (VD: "40%", "90 phút", "3 lần/ngày")
   - HOẶC TECHNIQUE: step-by-step rõ ràng
   - HOẶC PRINCIPLE: framework/mindset cụ thể

3. Final Scene — delivers REMAINING VALUE:
   - Case study HOẶC proof HOẶC CTA (save/share/try)

QUY TẮC NGHIÊM NGẶT:
- MỖI SCENE phải deliver ÍT NHẤT 1 điều CỤ THỂ (fact/technique/principle)
- MỖI SCENE phải có `gender` field: "male" hoặc "female" (bắt buộc)
- KHÔNG viết scene chỉ toàn câu hỏi mà không trả lời gì
- Scene hook có thể hỏi nhưng phải IMPLY/trả lời một phần ngay trong script đó
- Số scenes: tự quyết định dựa trên topic (2-5 scenes), không cố định 3

TRÁNH:
- Generic adjectives: "rất hiệu quả", "tuyệt vời" — thay bằng CONCRETE NUMBERS
- Câu hỏi không có answer trong video
- Câu hỏi engagement bait: "Bạn nghĩ sao?" — trả lời luôn

VÍ DỤ HOOK TỐT:
✅ "90-phút thay vì 25-phút Pomodoro — Olympic dùng phương pháp này để đạt peak state"
✅ "Đêm ngủ 8 tiếng là MYTH — athletes ngủ theo cách HOÀN TOÀN KHÁC và đây là lý do"
✅ "Pareto 80/20 có 1 TRƯỜNG HỢP NGOẠI LỆ — và nó quan trọng hơn nguyên tắc gốc"

---

CREATIVE_BRIEF REQUIREMENTS:
- visual_concept: mô tả what viewer nhìn thấy (setting, subjects, objects)
- emotion: cảm xúc nhân vật (intrigue, pride, surprise, etc.)
- camera_mood: góc/quay máy (medium shot, close-up, wide angle, etc.)
- unique_angle: điều độc đáo về cách frame scene này

ĐỊNH DẠNG JSON OUTPUT:
{{
  "scenes": [
    {{
      "id": 1,
      "scene_type": "hook",
      "script": "...",
      "character": "Teacher",
      "gender": "male",
      "delivers": "what viewer gets from this scene in 1 sentence",
      "creative_brief": {{
        "visual_concept": "setting + subjects + objects viewer sees",
        "emotion": "character emotion (intrigue, pride, surprise)",
        "camera_mood": "camera angle (medium shot, close-up, wide angle)",
        "unique_angle": "unique framing aspect"
      }},
      "image_prompt": "[visual_concept], [emotion], [art_style] art style, [environment] setting, [camera] camera, [lighting] lighting, [composition] composition",
      "lipsync_prompt": "..."
    }},
    ...
  ]
}}

CHỈ JSON object có "scenes" array, không markdown, không thêm field nào khác."""

    def _build_video_message_prompt(self, title: str, keywords: List[str],
                                     angle: str, description: str) -> str:
        """Build the prompt for Step 1: generating video_message.

        Returns a prompt instructing LLM to act as chief content strategist
        and produce a single video_message JSON object.
        """
        if not self._channel_config:
            raise ValueError("channel_config is required")

        kw_list_str = ", ".join(keywords) if keywords else ""

        return f"""Bạn là CHIEF CONTENT STRATEGIST cho kênh TikTok/Reels tiếng Việt.

NHIỆM VỤ:
Xác định "video_message" — thông điệp MANG ĐI của viewer sau khi xem video.

QUY TẮC:
1. video_message phải là 1-2 câu, NGẮN GỌN, CÓ Ý NGHĨA RÕ RÀNG
2. KHÔNG generic — phải CỤ THỂ, có con số HOẶC promise rõ ràng
3. Phải có "hook" — điều bất ngờ, thách thức, hoặc specific claim
4. Dựa vào NỘI DUNG THAM KHẢO, không bịa

NỘI DUNG THAM KHẢO:
{title}
Keywords: {kw_list_str}
Content angle: {angle}
Description:
{description[:1500]}

VÍ DỤ TỐT:
- "Phương pháp 90-phút giúp deep work HIỆU QUẢ HƠN 40% so với Pomodoro"
- "Nguyên tắc Pareto 80/20 không phải lúc nào cũng đúng — đây là version CẢI TIẾN"
- "Đêm ngủ 8 tiếng là SAI — thực tế Olympic dùng phương pháp khác"

OUTPUT JSON:
{{
  "video_message": "viết video_message ở đây"
}}

CHỈ JSON, không markdown, KHÔNG THÊM GÌ KHÁC."""

    def _parse_scenes(self, text: str) -> List[SceneConfig]:
        """Parse JSON scenes from LLM response text.

        Handles two formats:
        - Legacy: bare list [...]
        - New: {"video_message": "...", "scenes": [...]}

        Also handles markdown code fences that some LLM providers wrap JSON in.
        """
        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text)  # don't strip before this - we need whitespace before ```

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                scenes = parsed.get("scenes", [])
                if not isinstance(scenes, list):
                    scenes = [scenes]
            elif isinstance(parsed, list):
                scenes = parsed
            else:
                return []
            if scenes:
                return self._validate_scenes(scenes)
        except json.JSONDecodeError:
            # Try to find JSON array in text (legacy fallback)
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, dict):
                        scenes = parsed.get("scenes", [parsed])
                    elif isinstance(parsed, list):
                        scenes = parsed
                    else:
                        return []
                    return self._validate_scenes(scenes) if scenes else []
                except json.JSONDecodeError:
                    pass
        return []

    def _extract_video_message(self, raw_text: str) -> Optional[str]:
        """Extract video_message from raw LLM JSON response."""
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed.get("video_message") or None
        except json.JSONDecodeError:
            pass
        return None

    def _generate_video_message(self, title: str, keywords: List[str],
                                 angle: str, description: str) -> str:
        """Generate video_message via dedicated LLM call.

        This is Step 1 of the two-step generation. The video_message is
        NEVER None — if LLM fails or returns empty, we raise after retries.

        Args:
            title: Topic title.
            keywords: Topic keywords list.
            angle: Content angle (tips, educational, etc.).
            description: Researched content used as source knowledge.

        Returns:
            Non-empty video_message string.

        Raises:
            RuntimeError: If LLM returns empty/null video_message after max retries.
        """
        from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
        from modules.pipeline.models import TechnicalConfig

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

        prompt = self._build_video_message_prompt(title, keywords, angle, description)

        @retry(
            stop=stop_after_attempt(self._llm.retry_attempts if self._llm else 3),
            wait=wait_exponential(multiplier=1, min=1, max=self._llm.retry_backoff_max if self._llm else 10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _call_llm():
            raw = llm.chat(prompt, max_tokens=self._llm.max_tokens if self._llm else 256)
            msg = self._extract_video_message(raw)
            if not msg:
                raise RuntimeError("LLM returned empty/null video_message")
            return msg

        video_message = _call_llm()
        logger.info(f"Generated video_message: {video_message[:80]}...")
        return video_message

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
            # Capture gender from LLM output
            char_gender = scene.get("gender")
            # Set 'characters' list format that SceneConfig.from_dict expects
            scene["characters"] = [{"name": char, "gender": char_gender}]
            # Remove singular 'character' key to avoid confusion in from_dict
            scene.pop("character", None)
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

    def update_idea_script(self, idea_id: int, script: ScriptOutput):
        """Update idea with generated script (ScriptOutput Pydantic model)."""
        try:
            from db import update_idea_script as db_update_idea_script
            # Serialize ScriptOutput to dict with clean nested dicts (strip None recursively)
            def _clean(obj):
                if isinstance(obj, dict):
                    return {k: _clean(v) for k, v in obj.items() if v is not None}
                if isinstance(obj, list):
                    return [_clean(item) for item in obj if item is not None]
                return obj
            script_dict = _clean(script.model_dump())
            db_update_idea_script(idea_id, script_dict)
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
