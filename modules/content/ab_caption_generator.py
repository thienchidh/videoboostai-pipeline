"""
modules/content/ab_caption_generator.py — A/B Caption Variant Generator

Extends CaptionGenerator to produce two distinct caption styles:
  Variant A — "Hook + Value" style: curiosity headline + body + CTA + hashtags
  Variant B — "Question + Engagement" style: engaging question + perspective + hashtags

Template-based generation (no external LLM dependency).

Usage:
    gen = ABCaptionGenerator()
    result = gen.generate_ab_captions(script, platform="tiktok")
    # result.variant_a  → GeneratedCaption for A
    # result.variant_b  → GeneratedCaption for B
"""

import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.content.caption_generator import (
    CaptionGenerator,
    GeneratedCaption,
    HASHTAG_SETS,
    CTA_TEMPLATES,
    HEADLINE_TEMPLATES,
)

logger = logging.getLogger(__name__)

# ── Prompt templates ────────────────────────────────────────────────────────────

_VARIANT_A_PROMPT = """Bạn là chuyên gia viết caption cho video TikTok/Facebook Reels.

Script video: "{script}"

Hãy viết caption biến thể A theo phong cách "Hook + Value" — tạo curiosity bằng headline gây sốc/bất ngờ, sau đó cung cấp giá trị trong body.

Định dạng JSON:
{{
  "headline": "Headline gây tò mò / sốc (dưới 10 chữ, không dấu gạch ngang)",
  "body": "Nội dung body truyền tải giá trị (1-2 câu, hấp dẫn, có thông tin hữu ích)",
  "cta": "Lời kêu gọi hành động (1 câu ngắn gọn)"
}}

Không giải thích, chỉ trả về JSON hợp lệ."""

_VARIANT_B_PROMPT = """Bạn là chuyên gia viết caption cho video TikTok/Facebook Reels.

Script video: "{script}"

Hãy viết caption biến thể B theo phong cách "Question + Engagement" — đặt câu hỏi gây tương tác ở đầu, sau đó chia sẻ góc nhìn/câu chuyện cá nhân.

Định dạng JSON:
{{
  "headline": "Câu hỏi gây tương tác hoặc góc nhìn cá nhân (dưới 10 chữ)",
  "body": "Body chia sẻ góc nhìn / câu chuyện (1-2 câu, gần gũi, có cảm xúc)",
  "cta": "Lời kêu gọi hành động (1 câu ngắn gọn)"
}}

Không giải thích, chỉ trả về JSON hợp lệ."""

# ── Dataclass for paired result ────────────────────────────────────────────────

@dataclass
class ABCaptionResult:
    """Paired A/B caption result."""
    variant_a: GeneratedCaption
    variant_b: GeneratedCaption

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_a": self.variant_a.to_dict(),
            "variant_b": self.variant_b.to_dict(),
        }


# ── Generator ────────────────────────────────────────────────────────────────

class ABCaptionGenerator:
    """
    Generate two distinct caption variants (A/B) for the same script.

    Variant A — "Hook + Value": curiosity headline + informative body
    Variant B — "Question + Engagement": question + personal perspective

    Template-based only (no external LLM dependency).
    """

    def __init__(self):
        pass

    def _extract_topic(self, script: str) -> str:
        words = re.findall(r"[a-zA-ZÀ-ỹ]{4,}", script.lower())
        if not words:
            return "nội dung"
        word_freq: Dict[str, int] = {}
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1
        return max(words, key=lambda w: len(w) + word_freq[w] * 0.5)

    def _detect_category(self, script: str) -> str:
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

    def _build_caption(
        self,
        parsed: Optional[Dict],
        style: str,
        topic: str,
        category: str,
        platform: str,
    ) -> GeneratedCaption:
        """Build a GeneratedCaption from template (parsed is always None)."""
        hashtag_set = HASHTAG_SETS.get(category, HASHTAG_SETS["general"])

        # Template fallback (LLM path removed)
        if style == "a":
            headline = random.choice(HEADLINE_TEMPLATES).format(topic=topic)
            body_sample = [
                f"Đây là điều {topic} mà ít người để ý.",
                f"{topic.title()} — bạn đã thử chưa?",
                f"Khám phá {topic} ngay hôm nay!",
            ]
        else:
            headline_samples = [
                f"Bạn có biết về {topic}?",
                f"{topic.title()} — bạn nghĩ sao?",
                f"Tại sao {topic} lại quan trọng?",
            ]
            headline = random.choice(headline_samples)
            body_sample = [
                f"Chia sẻ góc nhìn của bạn về {topic} nhé!",
                f"{topic.title()} — đây là quan điểm của mình.",
                f"Mình nghĩ {topic} rất đáng để tìm hiểu.",
            ]
        body = random.choice(body_sample)
        cta = random.choice(CTA_TEMPLATES)

        # Truncate body for TikTok
        if platform == "tiktok":
            body = body[:80].rsplit(" ", 1)[0] + "..." if len(body) > 80 else body

        # Build full caption
        if platform == "tiktok":
            prefix = "🔥" if style == "a" else "❓"
            lines = [f"{prefix} {headline}", body, cta, " ".join(hashtag_set[:5])]
        else:
            lines = [f"**{headline}**", body, f"👉 {cta}", " ".join(hashtag_set)]

        full = "\n".join(l for l in lines if l)
        return GeneratedCaption(
            headline=headline,
            body=body,
            hashtags=hashtag_set[:5],
            cta=cta,
            full_caption=full,
        )

    def generate_caption_variant_A(
        self,
        script: str,
        platform: str = "tiktok",
    ) -> GeneratedCaption:
        """
        Generate Variant A caption — "Hook + Value" style.
        Headline creates curiosity, body delivers value.
        """
        topic = self._extract_topic(script)
        category = self._detect_category(script)
        return self._build_caption(None, "a", topic, category, platform)

    def generate_caption_variant_B(
        self,
        script: str,
        platform: str = "tiktok",
    ) -> GeneratedCaption:
        """
        Generate Variant B caption — "Question + Engagement" style.
        Opens with a question to drive comments and engagement.
        """
        topic = self._extract_topic(script)
        category = self._detect_category(script)
        return self._build_caption(None, "b", topic, category, platform)

    def generate_ab_captions(
        self,
        script: str,
        platform: str = "tiktok",
    ) -> ABCaptionResult:
        """
        Generate both A and B caption variants for the same script.
        Returns ABCaptionResult with variant_a and variant_b.
        """
        variant_a = self.generate_caption_variant_A(script, platform)
        variant_b = self.generate_caption_variant_B(script, platform)
        return ABCaptionResult(variant_a=variant_a, variant_b=variant_b)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_script = (
        sys.argv[1] if len(sys.argv) > 1
        else "Hải sản là nguồn dinh dưỡng tuyệt vời cho sức khỏe. "
             "Ăn hải sản đúng cách sẽ giúp bạn sống khỏe hơn mỗi ngày."
    )
    platform = sys.argv[2] if len(sys.argv) > 2 else "tiktok"

    gen = ABCaptionGenerator()
    result = gen.generate_ab_captions(test_script, platform)

    print(f"\n=== Variant A ({platform}) ===")
    print(result.variant_a.full_caption)

    print(f"\n=== Variant B ({platform}) ===")
    print(result.variant_b.full_caption)

    print("\n=== JSON ===")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))