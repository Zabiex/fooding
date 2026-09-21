"""Agent tools.

These are plain async functions. They are registered onto the Agent in
`nutrition_agent.py`, which means they can be imported and unit-tested with a
hand-built `RunContext` and a fake `Repositories` — no model call needed.

Docstrings matter: PydanticAI turns them into the tool description and the
per-parameter descriptions that Gemini actually reads.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from ..domain.models import (
    DailySummary,
    EntrySource,
    Ingredient,
    LogEntryDraft,
    MealLogged,
    MealType,
    Nutrition,
    RecipeDraft,
    RecipeMatch,
    RecipeSaved,
)
from ..services import nutrition as nutrition_service
from ..services.timeframes import parse_day_offset
from .dependencies import AgentDeps

logger = logging.getLogger(__name__)

MAX_SUMMARY_ENTRIES = 30


def _validate_macros(nutrition: Nutrition, label: str) -> None:
    """Bounce obviously inconsistent estimates back to the model."""
    if not nutrition_service.macros_are_consistent(nutrition):
        derived = nutrition_service.implied_calories(nutrition)
        raise ModelRetry(
            f"The macros for {label} do not match the calories: "
            f"{nutrition.protein_g:g} g protein + {nutrition.carbs_g:g} g carbs + "
            f"{nutrition.fat_g:g} g fat imply about {derived:.0f} kcal, but you said "
            f"{nutrition.calories:.0f} kcal. Recheck using 4/4/9 kcal per gram and call the tool again."
        )


# =============================================================================
# 1. create_recipe
# =============================================================================
async def create_recipe(
    ctx: RunContext[AgentDeps],
    name: str,
    calories_per_serving: float,
    servings: float = 1.0,
    protein_g_per_serving: float = 0.0,
    carbs_g_per_serving: float = 0.0,
    fat_g_per_serving: float = 0.0,
    fiber_g_per_serving: float = 0.0,
    description: str | None = None,
    ingredients: list[Ingredient] | None = None,
    tags: list[str] | None = None,
    overwrite_existing: bool = True,
) -> RecipeSaved:
    """Save a recipe to this user's personal recipe book.

    Use this when the user describes a dish they cooked or want to remember, so
    they can log it later by name without re-estimating it.

    Args:
        name: Short recipe name, e.g. "Overnight oats with berries".
        calories_per_serving: Kilocalories in ONE serving, not the whole batch.
        servings: How many servings the full recipe yields.
        protein_g_per_serving: Grams of protein in one serving.
        carbs_g_per_serving: Grams of carbohydrate in one serving.
        fat_g_per_serving: Grams of fat in one serving.
        fiber_g_per_serving: Grams of fiber in one serving.
        description: Optional method or notes.
        ingredients: Optional ingredient list with quantities and units.
        tags: Optional labels such as "vegetarian", "meal-prep".
        overwrite_existing: Replace a recipe of the same name if one exists.
    """
    per_serving = Nutrition(
        calories=calories_per_serving,
        protein_g=protein_g_per_serving,
        carbs_g=carbs_g_per_serving,
        fat_g=fat_g_per_serving,
        fiber_g=fiber_g_per_serving,
    )
    _validate_macros(per_serving, f"the recipe '{name}'")

    draft = RecipeDraft(
        name=name,
        description=description,
        servings=servings,
        ingredients=ingredients or [],
        nutrition_per_serving=per_serving,
        tags=tags or [],
    )

    recipe, was_updated = await ctx.deps.repos.recipes.save(
        ctx.deps.user_id, draft, overwrite_existing=overwrite_existing
    )
    logger.info(
        "recipe_saved user=%s recipe=%s updated=%s",
        ctx.deps.user.telegram_user_id,
        recipe.id,
        was_updated,
    )
    return RecipeSaved(
        recipe_id=recipe.id,
        name=recipe.name,
        servings=recipe.servings,
        nutrition_per_serving=recipe.nutrition_per_serving.rounded(),
        was_updated=was_updated,
    )


# =============================================================================
# 2. log_meal
# =============================================================================
async def log_meal(
    ctx: RunContext[AgentDeps],
    description: str,
    calories_per_serving: float = 0.0,
    servings: float = 1.0,
    meal_type: MealType = MealType.OTHER,
    protein_g_per_serving: float = 0.0,
    carbs_g_per_serving: float = 0.0,
    fat_g_per_serving: float = 0.0,
    fiber_g_per_serving: float = 0.0,
    recipe_id: str | None = None,
    confidence: float | None = None,
    hours_ago: float = 0.0,
) -> MealLogged:
    """Log something the user ate or drank into their food diary.

    If `recipe_id` is given, the stored recipe's nutrition is used and the
    `*_per_serving` arguments are ignored — call `find_recipe` first to get the
    id rather than estimating a dish the user has already saved.

    Args:
        description: What was eaten, e.g. "two scrambled eggs on toast".
        calories_per_serving: Kilocalories in ONE serving of this item.
        servings: How many servings the user actually ate.
        meal_type: breakfast, lunch, dinner, snack, drink or other.
        protein_g_per_serving: Grams of protein in one serving.
        carbs_g_per_serving: Grams of carbohydrate in one serving.
        fat_g_per_serving: Grams of fat in one serving.
        fiber_g_per_serving: Grams of fiber in one serving.
        recipe_id: Id of one of this user's saved recipes, if this meal was it.
        confidence: Your confidence in the estimate, 0 to 1.
        hours_ago: How long ago it was eaten. 0 means now; 3 means three hours ago.
    """
    deps = ctx.deps
    resolved_recipe_id: UUID | None = None
    per_serving: Nutrition

    if recipe_id:
        try:
            resolved_recipe_id = UUID(recipe_id)
        except ValueError as exc:
            raise ModelRetry(
                f"'{recipe_id}' is not a valid recipe id. Call find_recipe to get a real one, "
                "or omit recipe_id and estimate the nutrition yourself."
            ) from exc

        # Fetch the recipe by id from the shared recipe store. It may belong
        # to another user; that's allowed now and will be logged into the
        # caller's diary as provided.
        recipe = await deps.repos.recipes.get(resolved_recipe_id)
        if recipe is None:
            raise ModelRetry(
                "That recipe id does not exist. Call find_recipe first, or log the meal with your own estimate."
            )
        per_serving = recipe.nutrition_per_serving
        if not description.strip():
            description = recipe.name
    else:
        if calories_per_serving <= 0:
            raise ModelRetry(
                "calories_per_serving must be greater than zero when no recipe_id is given. "
                "Estimate the energy content of the food and call log_meal again."
            )
        per_serving = Nutrition(
            calories=calories_per_serving,
            protein_g=protein_g_per_serving,
            carbs_g=carbs_g_per_serving,
            fat_g=fat_g_per_serving,
            fiber_g=fiber_g_per_serving,
        )
        _validate_macros(per_serving, f"'{description}'")

    if servings <= 0:
        raise ModelRetry("servings must be greater than zero.")

    logged_at = deps.now_local() - timedelta(hours=max(0.0, hours_ago))

    draft = LogEntryDraft(
        description=description.strip(),
        meal_type=meal_type,
        source=deps.input_source,
        servings=servings,
        nutrition_per_serving=per_serving,
        recipe_id=resolved_recipe_id,
        confidence=confidence,
        raw_input=None,
        logged_at=logged_at,
    )

    entry = await deps.repos.log_entries.create(
        deps.user_id, draft, timezone_name=deps.timezone
    )

    # Give the model the running total so its confirmation message is accurate.
    day = logged_at.date()
    entries = await deps.repos.log_entries.list_for_day(deps.user_id, day, deps.timezone)
    summary = nutrition_service.build_daily_summary(
        user=deps.user, day=day, entries=entries, include_entries=False
    )

    logger.info(
        "meal_logged user=%s entry=%s kcal=%.0f",
        deps.user.telegram_user_id,
        entry.id,
        entry.nutrition.calories,
    )

    return MealLogged(
        entry_id=entry.id,
        description=entry.description,
        meal_type=entry.meal_type,
        servings=entry.servings,
        nutrition_logged=entry.nutrition.rounded(),
        logged_at=entry.logged_at,
        day_total_calories=summary.totals.calories,
        calories_remaining=summary.calories_remaining,
    )


# =============================================================================
# 3. get_daily_summary
# =============================================================================
async def get_daily_summary(
    ctx: RunContext[AgentDeps],
    day_offset: int = 0,
    include_entries: bool = True,
) -> DailySummary:
    """Get this user's totals for a single day in their own timezone.

    Args:
        day_offset: 0 for today, -1 for yesterday, -7 for a week ago today.
        include_entries: Include the individual log entries, not just totals.
    """
    deps = ctx.deps
    if day_offset > 0:
        raise ModelRetry("day_offset cannot be in the future. Use 0 for today or a negative number.")

    day = parse_day_offset(day_offset, deps.timezone)
    entries = await deps.repos.log_entries.list_for_day(deps.user_id, day, deps.timezone)

    summary = nutrition_service.build_daily_summary(
        user=deps.user,
        day=day,
        entries=entries,
        include_entries=include_entries,
    )
    if len(summary.entries) > MAX_SUMMARY_ENTRIES:
        summary = summary.model_copy(update={"entries": summary.entries[-MAX_SUMMARY_ENTRIES:]})
    return summary


# =============================================================================
# 4. find_recipe (supporting tool)
# =============================================================================
async def find_recipe(
    ctx: RunContext[AgentDeps],
    query: str,
    limit: int = 5,
) -> list[RecipeMatch]:
    """Search this user's saved recipes by name before estimating from scratch.

    Args:
        query: Words from the dish name, e.g. "oats" or "chicken curry".
        limit: Maximum number of matches to return.
    """
    recipes = await ctx.deps.repos.recipes.search(
        query, limit=max(1, min(limit, 10))
    )
    return [
        RecipeMatch(
            recipe_id=recipe.id,
            name=recipe.name,
            servings=recipe.servings,
            nutrition_per_serving=recipe.nutrition_per_serving.rounded(),
        )
        for recipe in recipes
    ]


ALL_TOOLS = [create_recipe, log_meal, get_daily_summary, find_recipe]
