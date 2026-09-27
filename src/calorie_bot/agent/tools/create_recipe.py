"""Save a recipe to the current user's recipe book."""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from ...domain.models import Ingredient, Nutrition, RecipeDraft, RecipeSaved
from ..dependencies import AgentDeps
from .common import validate_macros

logger = logging.getLogger(__name__)


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
    preparation_instructions: str | None = None,
    source_url: str | None = None,
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
        description: Optional notes about the recipe.
        preparation_instructions: Ordered steps explaining how to prepare the recipe.
        source_url: URL where the recipe came from, if the user provided one.
        ingredients: Optional ingredient list with quantities, units, and measurement systems.
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
    validate_macros(per_serving, f"the recipe '{name}'")

    draft = RecipeDraft(
        name=name,
        description=description,
        preparation_instructions=preparation_instructions,
        source_url=ctx.deps.source_url or source_url,
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