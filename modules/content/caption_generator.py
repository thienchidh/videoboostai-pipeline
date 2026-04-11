"""
modules/content/caption_generator.py — Auto-generate social media captions

Generates engaging captions for TikTok/Facebook Reels from video script.
Supports local LLM (ollama) or template-based fallback.

No API costs — designed for budget-exhausted development mode.
"""

import json
import logging
import random
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GeneratedCaption:
    """Output from caption generation."""
    headline: str
    body: str
    hashtags: List[str]
    cta: str  # Call-to-action
    full_caption: str  # Combined ready-to-post caption

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


# Template-based caption templates (Vietnamese market)
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

EMOJI_MAP = {
    "positive": ["😍", "🔥", "✨", "💯", "🙌", "❤️", "👍", "🤩"],
    "attention": ["👀", "🤔", "❓", "💡", "🎯"],
    "action": ["👉", "⬇️", "✅", "💪", "🎬"],
}


class CaptionGenerator:
    """Generate social media captions from video script."""

    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        model: str = "llama3.2",
        use_llm: bool = True,
    ):
        self.ollama_host = ollama_host
        self.model = model
        self.use_llm = use_llm and self._check_ollama()

    def _check_ollama(self) -> bool:
        """Check if ollama is available."""
        try:
            result = subprocess.run(
                ["curl", "-s", f"{self.ollama_host}/api/tags", "--max-time", "3"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _extract_topic(self, script: str) -> str:
        """Extract main topic/keyword from script."""
        # Remove filler words and get key nouns
        script_lower = script.lower()
        # Very simple extraction — take longest meaningful phrase
        words = re.findall(r"[a-zA-ZÀ-ỹ]{4,}", script_lower)
        if not words:
            return "nội dung"
        # Return most common or longest word as topic
        word_freq: Dict[str, int] = {}
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1
        # Prefer longer words (likely topic keywords)
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

    def generate_llm(self, script: str, platform: str = "tiktok") -> Optional[GeneratedCaption]:
        """Generate caption using local LLM via ollama."""
        if not self.use_llm:
            return None

        category = self._detect_category(script)
        topic = self._extract_topic(script)
        hashtag_set = HASHTAG_SETS.get(category, HASHTAG_SETS["general"])

        prompt = f"""Bạn là chuyên gia viết caption cho video TikTok/Facebook Reels.

Script video: "{script[:300]}"

Hãy viết 1 caption hấp dẫn cho video trên, theo định dạng JSON:
{{
  "headline": "Tiêu đề gây tò mò (dưới 10 chữ)",
  "body": "Nội dung caption (1-2 câu, hấp dẫn)",
  "cta": "Lời kêu gọi hành động (1 câu)"
}}

Không giải thích, chỉ trả về JSON hợp lệ."""

        try:
            result = subprocess.run(
                [
                    "curl", "-s", f"{self.ollama_host}/api/generate",
                    "-d", json.dumps({
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.8, "num_predict": 200}
                    }),
                    "--max-time", "30",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode != 0:
                logger.warning(f"Ollama call failed: {result.stderr}")
                return None

            response_text = result.stdout.strip()
            # Try to extract JSON from response
            try:
                data = json.loads(response_text)
                text = data.get("response", "")
            except json.JSONDecodeError:
                # Try to find JSON block
                import re
                m = re.search(r'\{.*\}', text := result.stdout.strip(), re.DOTALL)
                if m:
                    data = json.loads(m.group())
                else:
                    return None

            headline = data.get("headline", f"🔥 {topic.title()}")
            body = data.get("body", f"Nội dung thú vị về {topic}")
            cta = data.get("cta", random.choice(CTA_TEMPLATES))
            hashtags = hashtag_set[:5]

            full = self._combine_caption(headline, body, cta, hashtags, platform)
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

    def _combine_caption(
        self,
        headline: str,
        body: str,
        cta: str,
        hashtags: List[str],
        platform: str,
    ) -> str:
        if platform == "tiktok":
            lines = [f"🔥 {headline}", body, cta, " ".join(hashtags[:5])]
        else:
            lines = [f"**{headline}**", body, f"👉 {cta}", " ".join(hashtags)]
        return "\n".join(l for l in lines if l)

    def generate_template(
        self,
        script: str,
        platform: str = "tiktok",
    ) -> GeneratedCaption:
        """Generate caption using templates (no LLM required)."""
        topic = self._extract_topic(script)
        category = self._detect_category(script)
        hashtag_set = HASHTAG_SETS.get(category, HASHTAG_SETS["general"])

        headline = random.choice(HEADLINE_TEMPLATES).format(topic=topic)
        body = script[:100].rsplit(" ", 1)[0] + "..." if len(script) > 100 else script
        cta = random.choice(CTA_TEMPLATES)

        # Shorten for TikTok
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

    def generate(
        self,
        script: str,
        platform: str = "tiktok",
    ) -> GeneratedCaption:
        """Main entry point — generate caption for a script."""
        # Try LLM first, fall back to template
        if self.use_llm:
            result = self.generate_llm(script, platform)
            if result:
                logger.info(f"Caption generated via LLM for: {self._extract_topic(script)}")
                return result
            logger.info("Falling back to template caption generation")

        return self.generate_template(script, platform)

    def batch_generate(
        self,
        scripts: List[Dict[str, Any]],
        platform: str = "tiktok",
    ) -> List[GeneratedCaption]:
        """Generate captions for multiple scenes.

        Args:
            scripts: List of dicts with 'id' and 'script' keys
        """
        captions = []
        for scene in scripts:
            script = scene.get("script", "")
            if not script:
                continue
            cap = self.generate(script, platform)
            captions.append(cap)
        return captions


# CLI for testing
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_script = sys.argv[1] if len(sys.argv) > 1 else "Hải sản là nguồn dinh dưỡng tuyệt vời cho sức khỏe. Ăn hải sản đúng cách sẽ giúp bạn sống khỏe hơn."

    gen = CaptionGenerator(use_llm=False)
    cap = gen.generate(test_script, platform="tiktok")
    print("\n=== TikTok Caption ===")
    print(cap.for_tiktok())
    print("\n=== Facebook Caption ===")
    print(cap.for_facebook())
    print("\n=== JSON ===")
    print(json.dumps(cap.to_dict(), ensure_ascii=False, indent=2))
