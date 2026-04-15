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

logger = logging.getLogger(__name__)


@dataclass
class GeneratedCaption:
    """Output from caption generation."""
    headline: str
    body: str
    hashtags: List[str]
    cta: str
    full_caption: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "body": self.body,
            "hashtags": self.hashtags,
            "cta": self.cta,
            "full_caption": self.full_caption,
        }

    def for_tiktok(self) -> str:
        """Caption formatted for TikTok (shorter, emoji-heavy)."""
        lines = []
        if self.headline:
            lines.append(f"🔥 {self.headline}")
        if self.body:
            lines.append(self.body)
        if self.hashtags:
            lines.append(" ".join(self.hashtags[:5]))
        return "\n".join(lines)

    def for_facebook(self) -> str:
        """Caption formatted for Facebook (longer, engaging)."""
        lines = []
        if self.headline:
            lines.append(f"**{self.headline}**\n")
        if self.body:
            lines.append(f"{self.body}\n")
        if self.cta:
            lines.append(f"👉 {self.cta}\n")
        if self.hashtags:
            lines.append(" ".join(self.hashtags))
        return "\n".join(lines)


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

    def _generate_via_llm(self, script: str, platform: str) -> Optional[GeneratedCaption]:
        """Generate caption via LLM provider."""
        if self._llm is None:
            return None

        platform_label = "TikTok" if platform == "tiktok" else "Facebook"
        system = (
            f"You are a professional {platform_label} Reels caption writer for Vietnamese audience.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- You MUST respond with ONLY valid JSON — no markdown, no text before or after\n"
            "- headline: string, under 10 words, curiosity hook or bold statement, include fire emoji 🔥\n"
            "- body: string, 150-300 chars, story-telling style in Vietnamese, natural like speaking to viewer\n"
            "- cta: string, natural call-to-action or question to engage viewer\n"
            "- hashtags: array of 5-8 strings, each starting with #, relevant to the script content"
        )
        user = (
            f"Write a caption for a video. Script: \"{script[:800]}\"\n\n"
            f"Respond with ONLY this JSON format, nothing else:\n"
            f'{{"headline": "...", "body": "...", "cta": "...", "hashtags": ["#tag1", "#tag2"]}}'
        )

        try:
            response = self._llm.chat(user, system=system, max_tokens=1200)
            m = re.search(r'\{.*\}', response, re.DOTALL)
            if not m:
                logger.warning(f"LLM response missing JSON: {response[:100]}")
                return None

            data = json.loads(m.group())
            headline = data.get("headline", "🔥 Nội dung thú vị")
            body = data.get("body", "Nội dung video rất thú vị và hữu ích.")
            cta = data.get("cta") or random.choice(CTA_TEMPLATES)
            hashtags = data.get("hashtags") or ["#vietnamtiktok", "#fyp", "#trending"]
            if isinstance(hashtags, list) and len(hashtags) > 8:
                hashtags = hashtags[:8]
            full = self._combine_caption(headline, body, cta, hashtags, platform)

            logger.info(f"Caption generated via LLM")
            return GeneratedCaption(
                headline=headline,
                body=body,
                hashtags=hashtags,
                cta=cta,
                full_caption=full,
            )
        except Exception as e:
            logger.warning(f"LLM caption generation failed: {e}")
            return None

    def generate(self, script: str, platform: str = "tiktok") -> GeneratedCaption:
        """Generate caption. Uses LLM, falls back to template."""
        result = self._generate_via_llm(script, platform)
        if result:
            return result
        logger.info("Falling back to template caption generation")
        return self._generate_template(script, platform)

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