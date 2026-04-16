"""
modules/content/caption_generator.py — Auto-generate social media captions

Uses LLM provider via PluginRegistry for caption generation.
Falls back to template-based captions if LLM is unavailable.

Usage:
    # Default: use MiniMax from PluginRegistry
    gen = CaptionGenerator()
    caption = gen.generate("video script text", "tiktok")

    # Custom provider
    gen = CaptionGenerator(llm_provider=custom_llm_provider)
"""

import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.plugins import get_provider
from modules.pipeline.exceptions import CaptionGenerationError

logger = logging.getLogger(__name__)


@dataclass
class GeneratedCaption:
    """Output from caption generation with chain-of-thought."""
    thought_process: str   # NEW: internal reasoning from CoT
    insight: str          # NEW: contrarian hook
    headline: str
    body: str
    hashtags: List[str]
    cta: str
    full_caption: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thought_process": self.thought_process,
            "insight": self.insight,
            "headline": self.headline,
            "body": self.body,
            "hashtags": self.hashtags,
            "cta": self.cta,
            "full_caption": self.full_caption,
        }

HEADLINE_TEMPLATES = [
    "Bạn chưa biết điều này về {topic}",
    "Sự thật ít người biết về {topic}",
    "Cách {topic} thay đổi cuộc sống của bạn",
    " Bí kíp về {topic} ai cũng nên biết",
    "Tại sao {topic} lại quan trọng đến vậy?",
    "Những điều {topic} mà bạn chưa nghe bao giờ",
    "Cách để {topic} hiệu quả nhất",
    "Thủ thuật {topic} ít người dùng",
]

CTA_TEMPLATES = [
    "Đừng quên LIKE và SHARE để ủng hộ kênh!",
    "Follow để không bỏ lỡ những video tiếp theo nhé!",
    "Comment xem bạn nghĩ sao về điều này!",
    "Lưu lại để xem lại khi cần nhé!",
    "Chia sẻ cho bạn bè cùng xem nào!",
    "Đăng ký kênh và bật thông báo để không bỏ lỡ!",
    "Tag người bạn cần xem video này!",
    "LIKE nếu bạn thấy video hữu ích!",
]

HASHTAG_SETS = {
    "productivity": [
        "#nangsuatlaoviec", "#thoigian", "#congviec", "#moilame",
        "#cuocsong", "#thanhluu", "#tuanlamviec", "#motivational"
    ],
    "seafood": [
        "#haiisan", "#amthuc", "#monngon", "#haisan",
        "#anhchivlog", "#foodtiktok", "#tinhhoaculinary", "#douyin"
    ],
    "business": [
        "#kinhdoanh", "#khanhhoa", "#startup", "#entrepreneur",
        "#business", "#thanhcong", "#taichinh", "#ceo"
    ],
    "tech": [
        "#congnghe", "#ai", "#technology", "#innovation",
        "#future", "#smartphone", "#laptop", "#tech"
    ],
    "lifestyle": [
        "#lifestyle", "#cuocsong", "#xuhuong", "#vietnamtiktok",
        "#songtot", "#sangkhoe", "#thichly", "#fyp"
    ],
    "general": [
        "#vietnamtiktok", "#fyp", "#trending", "#viral",
        "#foryou", "#explore", "#contentcreator", "#motivation"
    ],
}


class CaptionGenerator:
    """Generate social media captions from video script via LLM provider."""

    def __init__(self, llm_provider=None):
        """
        Args:
            llm_provider: LLM provider instance (must have chat() method).
                         If None, uses MiniMaxLLMProvider from PluginRegistry.
        """
        if llm_provider is not None:
            self._llm = llm_provider
        else:
            provider_cls = get_provider("llm", "minimax")
            if provider_cls is None:
                raise ValueError("No LLM provider registered for 'minimax' — cannot generate captions")
            import os
            api_key = os.getenv("MINIMAX_API_KEY", "")
            self._llm = provider_cls(api_key=api_key) if api_key else None

    def _extract_topic(self, script: str) -> str:
        """Extract main topic/keyword from script."""
        script_lower = script.lower()
        words = re.findall(r"[a-zA-ZÀ-ỹ]{4,}", script_lower)
        if not words:
            return "nội dung"
        word_freq: Dict[str, int] = {}
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1
        return max(words, key=lambda w: len(w) + word_freq[w] * 0.5)

    def _detect_category(self, script: str) -> str:
        """Detect category from script keywords."""
        script_lower = script.lower()
        scores: Dict[str, int] = {}
        for cat, keywords in {
            "productivity": ["năng suất", "làm việc", "thời gian", "công việc", "hiệu quả", "mục tiêu"],
            "seafood": ["hải sản", "tôm", "cá", "mực", "ghẹ", "nấu", "ăn", "ngon"],
            "business": ["kinh doanh", "bán", "tiền", "thu nhập", "khách hàng", "marketing"],
            "tech": ["công nghệ", "app", "ứng dụng", "AI", "internet", "thiết bị"],
        }.items():
            scores[cat] = sum(1 for kw in keywords if kw in script_lower)
        if scores:
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                return best
        return "general"

    def _combine_caption(self, headline: str, body: str, cta: str,
                        hashtags: List[str], platform: str) -> str:
        if platform == "tiktok":
            lines = [f"🔥 {headline}", body, cta, " ".join(hashtags[:5])]
        else:
            lines = [f"**{headline}**", body, f"👉 {cta}", " ".join(hashtags)]
        return "\n".join(l for l in lines if l)

    def _generate_via_llm(self, script: str, platform: str) -> GeneratedCaption:
        """Generate caption via LLM with chain-of-thought prompting.

        Raises CaptionGenerationError on any failure (no defaults, no fallback).
        """
        if self._llm is None:
            raise CaptionGenerationError("llm_unavailable")

        if platform == "tiktok":
            system = (
                "Bạn là chuyên gia viết caption cho video TikTok/Reels Vietnamese.\n"
                "CRITICAL: Bạn PHẢI trả lời CHỈ có JSON hợp lệ, không có gì khác.\n\n"
                "CHUỖI SUY NGHĨ (chain-of-thought):\n"
                "1. Đọc script và phân tích:\n"
                "   - Điều bất ngờ/contrarian insight là gì?\n"
                "   - Key message chính là gì?\n"
                "   - Audience pain point là gì?\n"
                "2. Viết caption theo format bên dưới\n\n"
                "FORMAT JSON (bắt buộc - thiếu field = fail):\n"
                '{\n'
                '  "thought_process": "Chuỗi suy nghĩ của bạn khi phân tích script (1-2 câu)",\n'
                '  "insight": "Contrarian hook rút gọn 1-2 câu, gây tò mò mạnh nhất",\n'
                '  "headline": "🔥 headline dưới 10 từ, curiosity hook hoặc bold statement",\n'
                '  "body": "150 chars max, direct, conversational, viết như đang nói chuyện với viewer",\n'
                '  "cta": "CTA ngắn gọn dưới 15 từ, tự nhiên, kêu hành động cụ thể",\n'
                '  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]\n'
                "}\n\n"
                "RULES:\n"
                "- headline phải có fire emoji 🔥\n"
                "- body không quá 150 ký tự\n"
                "- hashtags phải là array có đúng 5 items, mỗi item phải bắt đầu bằng #\n"
                "- Không viết thêm giải thích gì khác ngoài JSON"
            )
            expected_hashtag_count = 5
        else:
            system = (
                "Bạn là chuyên gia viết caption cho Facebook post Vietnamese.\n"
                "CRITICAL: Bạn PHẢI trả lời CHỈ có JSON hợp lệ, không có gì khác.\n\n"
                "CHUỖI SUY NGHĨ (chain-of-thought):\n"
                "1. Đọc script và phân tích:\n"
                "   - Điều bất ngờ/contrarian insight là gì?\n"
                "   - Key message chính là gì?\n"
                "   - Audience pain point là gì?\n"
                "2. Viết caption theo format bên dưới\n\n"
                "FORMAT JSON (bắt buộc - thiếu field = fail):\n"
                '{\n'
                '  "thought_process": "Chuỗi suy nghĩ của bạn khi phân tích script (1-2 câu)",\n'
                '  "insight": "Contrarian hook rút gọn 1-2 câu, gây tò mò mạnh nhất",\n'
                '  "headline": "**headline dưới 10 từ, bold statement**",\n'
                '  "body": "300 chars, có context, có giá trị, viết tự nhiên như storyteller",\n'
                '  "cta": "Câu hỏi gợi discussion, tag bạn bè, hoặc kêu hành động cụ thể",\n'
                '  "hashtags": ["#tag1", "#tag2", "#tag3"]\n'
                "}\n\n"
                "RULES:\n"
                "- headline không cần emoji, dùng **bold** cho emphasis\n"
                "- body tối đa 300 ký tự\n"
                "- hashtags phải là array có đúng 3 items, mỗi item phải bắt đầu bằng #\n"
                "- Không viết thêm giải thích gì khác ngoài JSON"
            )
            expected_hashtag_count = 3

        user = f'Video script:\n"{script[:800]}"\n\nViết caption theo format JSON ở trên.'

        # Retry logic: 1 retry on failure (max 2 attempts total)
        last_error = None
        for attempt in range(2):
            try:
                response = self._llm.chat(user, system=system, max_tokens=1200)
                m = re.search(r'\{.*\}', response, re.DOTALL)
                if not m:
                    raise CaptionGenerationError(
                        "json_parse_error",
                        ValueError(f"No JSON found in response: {response[:100]}")
                    )

                data = json.loads(m.group())

                # Strict field presence check - all 6 fields required
                required_fields = ["thought_process", "insight", "headline", "body", "cta", "hashtags"]
                for field in required_fields:
                    if field not in data:
                        raise CaptionGenerationError(
                            f"missing_field:{field}",
                            ValueError(f"Response missing required field: {field}")
                        )
                    if data[field] is None or (isinstance(data[field], str) and not data[field].strip()):
                        raise CaptionGenerationError(
                            f"missing_field:{field}",
                            ValueError(f"Field '{field}' is empty")
                        )

                # Validate hashtags structure and count
                if not isinstance(data["hashtags"], list):
                    raise CaptionGenerationError(
                        "invalid_field:hashtags",
                        ValueError("hashtags must be a list")
                    )
                if len(data["hashtags"]) != expected_hashtag_count:
                    raise CaptionGenerationError(
                        "invalid_field:hashtags",
                        ValueError(f"{platform} requires exactly {expected_hashtag_count} hashtags, got {len(data['hashtags'])}")
                    )

                # Build full_caption pre-formatted
                if platform == "tiktok":
                    full = "\n".join([
                        f"🔥 {data['headline']}",
                        data['body'],
                        data['cta'],
                        " ".join(data['hashtags']),
                    ])
                else:
                    full = "\n".join([
                        f"**{data['headline']}**",
                        data['body'],
                        f"👉 {data['cta']}",
                        " ".join(data['hashtags']),
                    ])

                logger.info(f"Caption generated via LLM (CoT mode)")
                return GeneratedCaption(
                    thought_process=data["thought_process"],
                    insight=data["insight"],
                    headline=data["headline"],
                    body=data["body"],
                    hashtags=data["hashtags"],
                    cta=data["cta"],
                    full_caption=full,
                )

            except CaptionGenerationError as e:
                # json_parse_error or missing_field from our validation -> retry once
                if attempt == 0 and e.reason == "json_parse_error":
                    last_error = e.original_error
                    continue  # Retry
                raise  # Already retried or not json_parse_error, re-raise
            except Exception as e:
                last_error = e
                continue  # Retry

        # Both attempts failed
        raise CaptionGenerationError(
            "json_parse_error",
            last_error or ValueError("Unknown error after retries")
        )

    def generate(self, script: str, platform: str = "tiktok") -> GeneratedCaption:
        """Generate caption via LLM only. No fallback."""
        return self._generate_via_llm(script, platform)

    def _generate_template(self, script: str, platform: str) -> GeneratedCaption:
        """Generate caption using templates (fallback when LLM unavailable)."""
        topic = self._extract_topic(script)
        category = self._detect_category(script)
        hashtag_set = HASHTAG_SETS.get(category, HASHTAG_SETS["general"])

        headline = random.choice(HEADLINE_TEMPLATES).format(topic=topic)
        body = script[:100].rsplit(" ", 1)[0] + "..." if len(script) > 100 else script
        cta = random.choice(CTA_TEMPLATES)

        if platform == "tiktok":
            body = body[:80].rsplit(" ", 1)[0] + "..." if len(body) > 80 else body

        full = self._combine_caption(headline, body, cta, hashtag_set, platform)
        return GeneratedCaption(
            headline=headline,
            body=body,
            hashtags=hashtag_set[:5],
            cta=cta,
            full_caption=full,
        )

    def batch_generate(self, scripts: List[Dict[str, Any]],
                       platform: str = "tiktok") -> List[GeneratedCaption]:
        """Generate captions for multiple scripts."""
        captions = []
        for scene in scripts:
            script = scene.get("script", "")
            if not script:
                continue
            cap = self.generate(script, platform)
            captions.append(cap)
        return captions


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_script = sys.argv[1] if len(sys.argv) > 1 else "Hải sản là nguồn dinh dưỡng tuyệt vời cho sức khỏe."
    gen = CaptionGenerator()
    cap = gen.generate(test_script, platform="tiktok")
    print("\n=== TikTok Caption ===")
    print(cap.for_tiktok())
    print("\n=== Facebook Caption ===")
    print(cap.for_facebook())
    print("\n=== JSON ===")
    print(json.dumps(cap.to_dict(), ensure_ascii=False, indent=2))