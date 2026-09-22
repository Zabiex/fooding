"""GenAI helpers: retry with exponential backoff and model fallbacks.

Reads primary model from settings (`GEMINI_MODEL`) and optional
fallback list from the environment variable `GEMINI_FALLBACK_MODELS`
(comma-separated). Uses `tenacity` to retry transient `APIError`s.

Usage:
    from calorie_bot.services.genai import generate_with_fallback
    text = generate_with_fallback("Summarize this...")
"""

from __future__ import annotations

import os
from typing import List

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

try:
    from google import genai
    from google.genai.errors import APIError
except Exception:  # pragma: no cover - allowed to import at runtime
    genai = None
    APIError = Exception

from ..config import get_settings

settings = get_settings()
client = genai.Client() if genai is not None else None


def _parse_fallback_models() -> List[str]:
    raw = os.getenv("GEMINI_FALLBACK_MODELS", "")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(APIError),
    reraise=True,
)
def _call_model_with_retry(model: str, prompt: str):
    if client is None:
        raise RuntimeError("google.genai client not installed")
    # The genai client may have different response shapes; this mirrors
    # the simple usage pattern and returns the textual content when possible.
    resp = client.models.generate_content(model=model, contents=prompt)
    return resp


def generate_with_fallback(prompt: str) -> str:
    """Generate text using the primary model and fallbacks on transient 503s.

    Primary model comes from settings.gemini_model. Optional environment
    variable `GEMINI_FALLBACK_MODELS` can provide comma-separated fallbacks.
    """
    primary = settings.gemini_model
    fallbacks = _parse_fallback_models()

    # Build ordered unique list: primary then fallbacks
    ordered = []
    seen = set()
    for m in ( [primary] + fallbacks ):
        if not m or m in seen:
            continue
        seen.add(m)
        ordered.append(m)

    last_exc: Exception | None = None
    for model_name in ordered:
        try:
            resp = _call_model_with_retry(model_name, prompt)
            # best-effort extract text
            text = getattr(resp, "text", None)
            if text:
                return text
            try:
                # try nested structure used by some clients
                return resp.output[0].content[0].text
            except Exception:
                return str(resp)
        except APIError as e:
            last_exc = e
            # if it's a 503-like transient error, try next model
            code = getattr(e, "code", None)
            if code == 503 or "503" in str(e):
                continue
            raise
        except Exception as e:
            last_exc = e
            # For any other error, re-raise (auth, bad request etc.)
            raise

    raise RuntimeError("All fallback models are currently unavailable") from last_exc


__all__ = ["generate_with_fallback"]
