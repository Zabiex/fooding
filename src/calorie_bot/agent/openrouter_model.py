"""Async OpenRouter-backed model for use with pydantic-ai.

This implements a minimal `request(messages, model_settings, model_request_parameters)`
async method that posts to OpenRouter's `/api/v1/chat/completions` and returns
text content. It's used as a drop-in replacement for `GoogleModel` when
`OPENROUTER_API_KEY` is configured.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import httpx
import os

logger = logging.getLogger(__name__)


class OpenRouterModel:
    def __init__(self, model: str, *, api_key: str | None = None, timeout: float = 30.0):
        # Accept either full URL or model id like 'google/gemini-3.5-flash'
        self.model = model
        self.timeout = timeout
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not configured")

    async def request(self, messages: List[Dict[str, Any]], model_settings: Any = None, model_request_parameters: Any = None) -> Any:
        """Send `messages` to OpenRouter and return the assistant text.

        `messages` is expected to be a list of dicts with `role` and `content`.
        """
        payload = {"model": self.model, "messages": messages}

        # allow callers to toggle reasoning via env var
        if os.getenv("OPENROUTER_REASONING", "false").lower() in ("1", "true", "yes"):
            payload["reasoning"] = {"enabled": True}

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                logger.debug("OpenRouterModel.request model=%s messages=%s", self.model, messages)
                r = await client.post(self.api_url, json=payload, headers=headers)
                r.raise_for_status()
            except Exception as exc:
                logger.exception("OpenRouter request failed")
                raise

        data = r.json()

        # Extract assistant text from common OpenRouter shapes
        try:
            choices = data.get("choices") or []
            if choices:
                first = choices[0]
                message = first.get("message") or first
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list) and content:
                        return str(content[0])
        except Exception:
            logger.debug("Failed to parse OpenRouter response shape, returning raw JSON")

        # Fallback: return full JSON string
        return str(data)


__all__ = ["OpenRouterModel"]
