"""Search the current user's saved recipes."""

from __future__ import annotations

from pydantic_ai import RunContext

from ...domain.models import RecipeMatch
from ..dependencies import AgentDeps


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