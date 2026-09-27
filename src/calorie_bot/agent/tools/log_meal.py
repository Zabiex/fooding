"""Log a meal and report the user's updated daily calorie total."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from ...domain.models import LogEntryDraft, MealLogged, MealType, Nutrition
from ...services import nutrition as nutrition_service
from ..dependencies import AgentDeps
from .common import validate_macros

logger = logging.getLogger(__name__)


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
        validate_macros(per_serving, f"'{description}'")

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