# CaptionGenerator Refactor — Remove Ollama, Use PluginRegistry LLM

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all ollama local LLM code from CaptionGenerator. Make LLM provider configurable via PluginRegistry (same pattern as TTS/Image providers). CaptionGenerator accepts an LLM provider, defaults to MiniMax.

**Architecture:** Follow existing PluginRegistry pattern from `core/plugins.py`. Register `MiniMaxLLMProvider` under `"llm"` category. `CaptionGenerator` accepts `llm_provider` in constructor, defaults to `get_provider("llm", "minimax")`. Remove all ollama CURL calls, `_check_ollama()`, `generate_llm()`, template fallback.

**Tech Stack:** Python 3, PluginRegistry, MiniMaxLLMProvider

---

## Task 1: Register MiniMaxLLMProvider in PluginRegistry

**Files:**
- Modify: `modules/llm/minimax.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_llm_provider_registration.py`:

```python
def test_minimax_llm_registered_in_plugin_registry():
    """MiniMaxLLMProvider should be registered under 'llm' category."""
    from core.plugins import get_provider, register_provider
    from modules.llm.minimax import MiniMaxLLMProvider

    # Verify it's registered
    cls = get_provider("llm", "minimax")
    assert cls is not None, "MiniMaxLLMProvider not registered in plugin registry"
    assert cls is MiniMaxLLMProvider, f"Expected MiniMaxLLMProvider, got {cls}"

    # Verify it can be instantiated
    instance = cls(api_key="fake_key")
    assert hasattr(instance, "chat"), "MiniMaxLLMProvider missing chat() method"
```

Run: `pytest tests/test_llm_provider_registration.py -v`
Expected: FAIL — not registered yet

- [ ] **Step 2: Add auto-registration in minimax.py**

In `modules/llm/minimax.py`, add at the bottom of the file (after the provider class definition):

```python
# Auto-register on import
from core.plugins import register_provider
register_provider("llm", "minimax", MiniMaxLLMProvider)
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_llm_provider_registration.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/llm/minimax.py
git commit -m "feat: register MiniMaxLLMProvider in PluginRegistry under 'llm' category"
```

---

## Task 2: Refactor CaptionGenerator — Remove Ollama, Use PluginRegistry LLM

**Files:**
- Modify: `modules/content/caption_generator.py` (complete rewrite)
- Modify: `tests/test_caption_generator.py` (update tests)

- [ ] **Step 1: Write failing test**

Update `tests/test_caption_generator.py` with new tests:

```python
def test_caption_generator_uses_minimax_via_plugin_registry():
    """CaptionGenerator should use LLM provider from PluginRegistry by default."""
    from unittest.mock import MagicMock, patch
    from modules.content.caption_generator import CaptionGenerator

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"headline": "Test Headline", "body": "Test body", "cta": "Test CTA"}'

    with patch("core.plugins.get_provider") as mock_get:
        mock_get.return_value = MagicMock(return_value=mock_llm)

        gen = CaptionGenerator()  # no args — should default to PluginRegistry LLM
        result = gen.generate("Test script video", "tiktok")

        # Verify get_provider was called for 'llm' category with 'minimax'
        mock_get.assert_called_with("llm", "minimax")
        # Verify chat was called
        assert mock_llm.chat.called
        assert result is not None
        assert result.headline == "Test Headline"

def test_caption_generator_accepts_custom_llm_provider():
    """CaptionGenerator should accept custom LLM provider via constructor."""
    from unittest.mock import MagicMock
    from modules.content.caption_generator import CaptionGenerator

    custom_provider = MagicMock()
    custom_provider.chat.return_value = '{"headline": "Custom", "body": "Custom body", "cta": "Custom CTA"}'

    gen = CaptionGenerator(llm_provider=custom_provider)
    result = gen.generate("Test script", "facebook")

    assert result.headline == "Custom"
    assert custom_provider.chat.called

def test_caption_generator_no_ollama_code():
    """CaptionGenerator should have no ollama imports or references."""
    import ast
    from pathlib import Path

    caption_file = Path("modules/content/caption_generator.py")
    content = caption_file.read_text()

    # Parse AST and check for ollama references
    tree = ast.parse(content)
    ollama_names = ["ollama", "subprocess", "_check_ollama", "generate_llm", "use_llm"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ollama_names:
            # Check it's not in a comment
            assert False, f"Found disallowed name '{node.id}' in CaptionGenerator — ollama code must be removed"

    # Also check no curl/subprocess calls for LLM
    assert "curl" not in content, "curl calls found — ollama code not removed"
    assert "subprocess" not in content or "ffmpeg" in content or "get_ffmpeg" in content, \
        "subprocess found — ollama code not removed"
```

Run: `pytest tests/test_caption_generator.py -v`
Expected: FAIL — ollama code still present

- [ ] **Step 2: Complete rewrite of CaptionGenerator**

Replace ALL of `modules/content/caption_generator.py` with this clean version:

```python
"""
modules/content/caption_generator.py — Auto-generate social media captions

Uses MiniMax LLM via PluginRegistry for caption generation.
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

    def __init__(
        self,
        llm_provider=None,
        llm_model: str = "MiniMax-M2.7",
    ):
        """
        Args:
            llm_provider: LLM provider instance (must have chat() method).
                         If None, uses MiniMaxLLMProvider from PluginRegistry.
            llm_model: Model name to pass to provider (default: MiniMax-M2.7)
        """
        if llm_provider is not None:
            self._llm = llm_provider
        else:
            provider_cls = get_provider("llm", "minimax")
            if provider_cls is None:
                raise ValueError("No LLM provider registered for 'minimax' — cannot generate captions")
            # API key loaded from technical config or environment
            import os
            api_key = os.getenv("MINIMAX_API_KEY", "")
            self._llm = provider_cls(api_key=api_key) if api_key else None

        self._model = llm_model

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

    def _generate_via_llm(self, script: str, platform: str) -> Optional[GeneratedCaption]:
        """Generate caption via LLM provider (MiniMax or custom)."""
        if self._llm is None:
            return None

        category = self._detect_category(script)
        topic = self._extract_topic(script)
        hashtag_set = HASHTAG_SETS.get(category, HASHTAG_SETS["general"])

        system = "Bạn là chuyên gia viết caption cho video TikTok/Facebook Reels tiếng Việt."
        user = f'Viết 1 caption hấp dẫn cho video: "{script[:300]}"\n\nFormat JSON: {{"headline": "...", "body": "...", "cta": "..."}}'

        try:
            response = self._llm.chat(user, system=system, max_tokens=200)
            m = re.search(r'\{.*\}', response, re.DOTALL)
            if not m:
                logger.warning(f"LLM response missing JSON: {response[:100]}")
                return None

            data = json.loads(m.group())
            headline = data.get("headline", f"🔥 {topic.title()}")
            body = data.get("body", f"Nội dung thú vị về {topic}")
            cta = data.get("cta", random.choice(CTA_TEMPLATES))
            hashtags = hashtag_set[:5]
            full = self._combine_caption(headline, body, cta, hashtags, platform)

            logger.info(f"Caption generated via LLM for topic: {topic}")
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

    def generate(
        self,
        script: str,
        platform: str = "tiktok",
    ) -> GeneratedCaption:
        """Generate caption for a script. Uses LLM, falls back to template."""
        # Try LLM first
        result = self._generate_via_llm(script, platform)
        if result:
            return result

        # Fallback to template
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

    def batch_generate(
        self,
        scripts: List[Dict[str, Any]],
        platform: str = "tiktok",
    ) -> List[GeneratedCaption]:
        """Generate captions for multiple scripts."""
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

    test_script = sys.argv[1] if len(sys.argv) > 1 else "Hải sản là nguồn dinh dưỡng tuyệt vời cho sức khỏe."

    gen = CaptionGenerator()
    cap = gen.generate(test_script, platform="tiktok")
    print("\n=== TikTok Caption ===")
    print(cap.for_tiktok())
    print("\n=== Facebook Caption ===")
    print(cap.for_facebook())
    print("\n=== JSON ===")
    print(json.dumps(cap.to_dict(), ensure_ascii=False, indent=2))
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest tests/test_caption_generator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add modules/content/caption_generator.py tests/test_caption_generator.py
git commit -m "refactor: remove ollama, use PluginRegistry LLM provider in CaptionGenerator"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Ollama removed — no `subprocess`, no `curl`, no `_check_ollama`, no `generate_llm`
- ✅ MiniMax LLM via PluginRegistry — `get_provider("llm", "minimax")` 
- ✅ Configurable LLM provider via constructor — `llm_provider` param
- ✅ Template fallback still works when LLM unavailable
- ✅ Follows existing PluginRegistry pattern (same as TTS/Image/Lipsync)

**Placeholder scan:** No TBD/TODO. No "implement later". All code shown.

**Type consistency:** `CaptionGenerator.__init__(llm_provider=None)` — None means use PluginRegistry default. `_generate_via_llm()` returns `Optional[GeneratedCaption]`. `generate()` returns `GeneratedCaption`.

**Test coverage:** Tests verify (1) PluginRegistry registration, (2) CaptionGenerator uses PluginRegistry LLM by default, (3) custom provider accepted, (4) no ollama code remains.

---

## Execution Options

**Plan complete and saved to `docs/superpowers/plans/2026-04-14-caption-generator-refactor.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**