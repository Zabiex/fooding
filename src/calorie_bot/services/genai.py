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
import requests
from requests import RequestException

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


def _call_openrouter(model_url: str, prompt: str):
    """Call an OpenRouter-style HTTP endpoint.

    - If `model_url` is a full URL (starts with http), POST to it.
    - Otherwise POST to the canonical OpenRouter completions endpoint
      and pass `model=model_url` in the JSON body.

    Tries to extract text from common fields in the JSON response.
    """
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY (or GOOGLE_API_KEY) not set for OpenRouter calls")
    # Use the OpenRouter chat completions endpoint and pass `messages`.
    url = "https://openrouter.ai/api/v1/chat/completions"

    # If caller provided a full OpenRouter model URL, extract the model id part.
    if model_url.startswith("http://") or model_url.startswith("https://"):
        parsed = urlparse(model_url)
        model_id = parsed.path.lstrip("/")
    else:
        model_id = model_url

    messages = [{"role": "user", "content": prompt}]
    json_body = {"model": model_id, "messages": messages}

    # Optionally enable reasoning if the environment requests it
    if os.getenv("OPENROUTER_REASONING", "false").lower() in ("1", "true", "yes"):
        json_body["reasoning"] = {"enabled": True}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, json=json_body, headers=headers, timeout=15)
        r.raise_for_status()
    except RequestException as e:
        raise APIError(str(e)) from e

    data = r.json()

    # Preferred OpenRouter shape: choices[0].message with content and optional reasoning_details
    try:
        choices = data.get("choices") or []
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message") or first
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    # Some providers use {'content': ['...']}
                    if isinstance(content, list) and content:
                        return str(content[0])
    except Exception:
        pass

    # Fall back to other known shapes
    for key in ("text", "output", "result"):
        if key in data and isinstance(data[key], str):
            return data[key]

    return str(data)


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
            # If model_name looks like an OpenRouter URL or mentions openrouter, use HTTP path
            if model_name.startswith("http://") or model_name.startswith("https://") or "openrouter.ai" in model_name:
                return _call_openrouter(model_name, prompt)

            # Prefer the google.genai client path when available
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
