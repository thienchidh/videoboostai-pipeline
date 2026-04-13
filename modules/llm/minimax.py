"""
modules/llm/minimax.py — MiniMax LLM provider (Anthropic-compatible API).
"""

import logging
from typing import Optional

from core.plugins import LLMProvider

logger = logging.getLogger(__name__)


class MiniMaxLLMProvider(LLMProvider):
    """MiniMax LLM via Anthropic-compatible API.

    API docs: https://platform.minimax.io/docs/api-reference/text-anthropic-api
    Models: MiniMax-M2.7, MiniMax-M2.5, MiniMax-M2.1
    """

    DEFAULT_URL = "https://api.minimax.io/anthropic/v1/messages"

    def __init__(self, api_key: str, model: str = "MiniMax-M2.7",
                 max_tokens: int = 1024, timeout: int = 60,
                 api_url: Optional[str] = None):
        """
        Args:
            api_key: MiniMax API key
            model: Model name (default: MiniMax-M2.7)
            max_tokens: Max tokens per response
            timeout: Request timeout in seconds
            api_url: Optional API URL override (reads from config if not provided)
        """
        if not api_key:
            raise ValueError("MiniMax API key is required")
        import requests
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.api_url = api_url or self.DEFAULT_URL
        # Reuse connection pool via session
        self._session = requests.Session()

    def chat(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        """
        Send a chat prompt to MiniMax LLM.

        Args:
            prompt: User prompt text
            system: Optional system prompt
            max_tokens: Override max tokens for this call

        Returns:
            Response text from LLM
        """
        messages = []
        if system:
            messages.append({"role": "assistant", "content": [{"type": "text", "text": system}]})
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

        body = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": messages,
        }

        resp = self._session.post(
            self.api_url,
            headers={
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
            },
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        # Strip thinking/reasoning blocks that MiniMax sometimes includes
        content = data.get("content", [])
        if isinstance(content, list) and content:
            text_parts = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            if text_parts:
                return "".join(text_parts)
        return ""
