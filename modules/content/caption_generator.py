"""
modules/content/caption_generator.py — Auto-generate social media captions via LLM

Uses LLM provider via PluginRegistry. No template fallback — any LLM failure
raises CaptionGenerationError.

Usage:
    # Default: use MiniMax from PluginRegistry
    gen = CaptionGenerator()
    caption = gen.generate("video script text", "tiktok")

    # Custom provider
    gen = CaptionGenerator(llm_provider=custom_llm_provider)
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from core.plugins import get_provider
from modules.pipeline.exceptions import CaptionGenerationError
from modules.pipeline.models import TechnicalConfig

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

class CaptionGenerator:
    """Generate social media captions from video script via LLM provider."""

    def __init__(self, llm_provider=None, technical_config: TechnicalConfig = None):
        """
        Args:
            llm_provider: LLM provider instance (must have chat() method).
                         If None, uses MiniMaxLLMProvider from PluginRegistry.
            technical_config: TechnicalConfig instance. If provided, API key is read
                             from technical_config.api_keys.minimax instead of env vars.
        """
        if llm_provider is not None:
            self._llm = llm_provider
        else:
            provider_cls = get_provider("llm", "minimax")
            if provider_cls is None:
                raise ValueError("No LLM provider registered for 'minimax' — cannot generate captions")
            if technical_config is not None:
                api_key = technical_config.api_keys.minimax
            else:
                import os
                api_key = os.getenv("MINIMAX_API_KEY", "")
            if not api_key:
                self._llm = None
            else:
                self._llm = provider_cls(api_key=api_key)

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
    print("\n=== Caption ===")
    print(cap.full_caption)
    print("\n=== JSON ===")
    print(json.dumps(cap.to_dict(), ensure_ascii=False, indent=2))