"""The PydanticAI agent itself: model + instructions + tool registration.

Nothing here knows about Telegram, and nothing here issues SQL. Swapping Gemini
for another provider is a change to `build_model` alone.
"""

from __future__ import annotations
import os
import logging

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings

from ..config import Settings
from .dependencies import AgentDeps
from .prompts import SYSTEM_INSTRUCTIONS, user_context_block
from .tools import ALL_TOOLS

logger = logging.getLogger(__name__)

NutritionAgent = Agent[AgentDeps, str]


def build_model(settings: Settings) -> GoogleModel:
    """Gemini 1.5 Flash through the Gemini API (Google AI Studio).

    Constructing the provider explicitly (rather than the `'google:gemini-1.5-flash'`
    shorthand) keeps the API key in our settings object instead of the ambient
    environment, and insulates us from the `google-gla:` -> `google:` prefix rename.
    """
    # If an OpenRouter key is configured prefer the OpenRouter provider by
    # returning a model id prefixed with `openrouter/` so pydantic-ai constructs
    # an OpenRouterProvider that uses the `OPENROUTER_API_KEY` from settings.
    openrouter_key = None
    try:
        openrouter_key = settings.openrouter_api_key.get_secret_value() if getattr(settings, "openrouter_api_key", None) else None
    except Exception:
        openrouter_key = None

    if openrouter_key:
        model_id = settings.gemini_model
        # Ensure the inner token has an upstream provider (e.g. 'google/..').
        if '/' not in model_id:
            model_id = f"google/{model_id}"
        # pydantic-ai expects a provider prefix separated by ':' so use 'openrouter:provider/model'
        return f"openrouter:{model_id}"

    provider = GoogleProvider(api_key=settings.google_api_key.get_secret_value())
    return GoogleModel(settings.gemini_model, provider=provider)


def build_agent(settings: Settings) -> NutritionAgent:
    agent: NutritionAgent = Agent(
        build_model(settings),
        deps_type=AgentDeps,
        output_type=str,
        instructions=SYSTEM_INSTRUCTIONS,
        tools=ALL_TOOLS,
        retries=2,
        model_settings=ModelSettings(temperature=0.2, max_tokens=1024),
    )

    @agent.instructions
    def _user_context(ctx) -> str:  # type: ignore[no-untyped-def]
        """Per-run context: who is speaking, their clock, their targets.

        On pydantic-ai < 1.0 this decorator is called `@agent.system_prompt`.
        """
        user = ctx.deps.user
        return user_context_block(
            display_name=user.display_name,
            local_time=ctx.deps.now_local().strftime("%A %d %B %Y, %H:%M"),
            timezone_name=user.timezone,
            calorie_target=user.daily_calorie_target,
            protein_target=user.protein_target_g,
        )

    logger.info("Nutrition agent built on model %s.", settings.gemini_model)
    return agent
