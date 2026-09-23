"""Orchestration between the transport (Telegram) and the agent.

The handler layer only ever calls `run_text` / `run_photo`. Everything about
dependency assembly, conversation history, per-user serialisation and timeouts
lives here, so a second transport (web, CLI, WhatsApp) would reuse it verbatim.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

from pydantic_ai import BinaryContent, UnexpectedModelBehavior
from pydantic_ai.exceptions import ModelHTTPError

try:
    from google.genai.errors import ClientError as GoogleClientError
except Exception:  # pragma: no cover
    GoogleClientError = None

try:  # `Usage` was renamed to `RunUsage` in pydantic-ai 1.x
    from pydantic_ai.usage import RunUsage
except ImportError:  # pragma: no cover
    from pydantic_ai.usage import Usage as RunUsage  # type: ignore[assignment]

from ..config import Settings
from ..db.repositories import Repositories
from ..domain.models import EntrySource, UserProfile
from .dependencies import AgentDeps
from .history import ConversationStore
from .nutrition_agent import NutritionAgent
from .prompts import (
    PHOTO_PROMPT,
    PHOTO_PROMPT_WITH_CAPTION,
    VIDEO_PROMPT,
    VIDEO_PROMPT_WITH_CAPTION,
)

logger = logging.getLogger(__name__)


class AgentError(RuntimeError):
    """Raised when a run fails in a way the user should hear about."""


@dataclass
class AgentReply:
    text: str
    usage: RunUsage | None = None


class AgentRunner:
    def __init__(
        self,
        *,
        agent: NutritionAgent,
        repos: Repositories,
        settings: Settings,
        history: ConversationStore | None = None,
    ) -> None:
        self._agent = agent
        self._repos = repos
        self._settings = settings
        self._history = history or ConversationStore(
            max_turns=settings.history_turns_kept,
            ttl_seconds=settings.history_ttl_seconds,
        )
        # One in-flight run per user: a second message queues instead of racing.
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    @property
    def max_video_bytes(self) -> int:
        return self._settings.max_video_bytes

    # -- public API -----------------------------------------------------------
    async def run_text(self, user: UserProfile, text: str) -> AgentReply:
        return await self._run(user, text, EntrySource.TEXT)

    async def run_photo(
        self,
        user: UserProfile,
        image_bytes: bytes,
        *,
        media_type: str = "image/jpeg",
        caption: str | None = None,
    ) -> AgentReply:
        if len(image_bytes) > self._settings.max_photo_bytes:
            raise AgentError("That image is too large for me to process. Try a smaller photo.")

        prompt_text = (
            PHOTO_PROMPT_WITH_CAPTION.format(caption=caption.strip())
            if caption and caption.strip()
            else PHOTO_PROMPT
        )
        prompt = [prompt_text, BinaryContent(data=image_bytes, media_type=media_type)]
        return await self._run(user, prompt, EntrySource.PHOTO)

    async def run_video(
        self,
        user: UserProfile,
        video_bytes: bytes,
        *,
        caption: str | None = None,
    ) -> AgentReply:
        if len(video_bytes) > self._settings.max_video_bytes:
            raise AgentError("That video is too large for me to process. Try a shorter video.")

        prompt_text = (
            VIDEO_PROMPT_WITH_CAPTION.format(caption=caption.strip())
            if caption and caption.strip()
            else VIDEO_PROMPT
        )
        prompt = [prompt_text, BinaryContent(data=video_bytes, media_type="video/mp4")]
        return await self._run(user, prompt, EntrySource.VIDEO)

    def reset(self, telegram_user_id: int) -> None:
        self._history.clear(telegram_user_id)

    # -- internals ------------------------------------------------------------
    async def _run(self, user: UserProfile, prompt, source: EntrySource) -> AgentReply:
        deps = AgentDeps(user=user, repos=self._repos, input_source=source)

        async with self._locks[user.telegram_user_id]:
            history = self._history.get(user.telegram_user_id)
            try:
                result = await asyncio.wait_for(
                    self._agent.run(prompt, deps=deps, message_history=history),
                    timeout=self._settings.agent_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                logger.warning("agent_timeout user=%s", user.telegram_user_id)
                raise AgentError(
                    "That took too long to work out. Could you try again, or describe it in fewer words?"
                ) from exc
            except UnexpectedModelBehavior as exc:
                logger.exception("agent_model_error user=%s", user.telegram_user_id)
                raise AgentError(
                    "I couldn't make sense of that one. Try describing the food and the portion size."
                ) from exc
            except (ModelHTTPError, GoogleClientError) as exc:
                # Try a local fallback (OpenRouter or fallback models) for transient
                # quota / rate-limit errors. Only applies for text prompts.
                logger.warning("Model HTTP error, attempting fallback: %s", exc)
                try:
                    from ..services.genai import generate_with_fallback

                    # Determine textual prompt
                    if isinstance(prompt, str):
                        text_prompt = prompt
                    elif isinstance(prompt, list) and prompt and isinstance(prompt[0], str):
                        text_prompt = prompt[0]
                    else:
                        raise

                    # Run the blocking helper in a thread to avoid blocking the event loop
                    fallback_text = await asyncio.to_thread(generate_with_fallback, text_prompt)
                    # Create a minimal result-like object to preserve usage=None
                    class _FallbackResult:
                        def __init__(self, output: str):
                            self.output = output
                            self.usage = None
                            self.new_messages = lambda: []

                    result = _FallbackResult(fallback_text)
                except Exception:
                    logger.exception("Fallback generation failed")
                    raise AgentError("The model is currently overloaded; try again in a moment.") from exc

            # Binary media is dropped from history: keeping it re-uploads the
            # file on every subsequent turn and burns tokens for nothing.
            self._history.extend(user.telegram_user_id, _strip_binary(result.new_messages()))

        logger.info(
            "agent_run user=%s source=%s requests=%s",
            user.telegram_user_id,
            source.value,
            getattr(result.usage, "requests", None),
        )
        return AgentReply(text=result.output, usage=result.usage)


def _strip_binary(messages):
    """Replace image parts in stored history with a short placeholder."""
    for message in messages:
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, list):
                part.content = [
                    "[media omitted from history]" if isinstance(item, BinaryContent) else item
                    for item in content
                ]
    return messages
