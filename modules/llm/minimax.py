"""
modules/llm/minimax.py — MiniMax LLM provider (Anthropic-compatible API).
"""

import json
import logging
from typing import Optional

from core.plugins import LLMProvider
from core.retry import retry_on_500

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

    @retry_on_500()
    def _call_api(self, url, headers, body):
        resp = self._session.post(url, headers=headers, json=body, timeout=self.timeout)
        if not resp.ok:
            resp.raise_for_status()
        return resp

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

        logger.debug(f"MiniMax API request: model={self.model}, max_tokens={max_tokens or self.max_tokens}")
        # Log truncated payload for readability
        payload_str = json.dumps(body, ensure_ascii=False, indent=2)
        if len(payload_str) > 2000:
            logger.debug(f"MiniMax API payload (truncated):\n{payload_str[:2000]}\n... [truncated {len(payload_str)-2000} chars]")
        else:
            logger.debug(f"MiniMax API payload:\n{payload_str}")

        try:
            resp = self._call_api(
                self.api_url,
                {
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                },
                body,
            )
            logger.debug(f"MiniMax API response status: {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
        response_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(response_str) > 1000:
            logger.debug(f"MiniMax API response (truncated):\n{response_str[:1000]}\n... [truncated {len(response_str)-1000} chars]")
        else:
            logger.debug(f"MiniMax API response:\n{response_str}")

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


# Auto-register on import
from core.plugins import register_provider
register_provider("llm", "minimax", MiniMaxLLMProvider)
