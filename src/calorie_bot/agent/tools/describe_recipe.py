"""Return ingredients and preparation instructions for saved recipes."""

from __future__ import annotations

from pydantic_ai import RunContext

from ...domain.models import RecipeDescription
from ..dependencies import AgentDeps


async def describe_recipe(
    ctx: RunContext[AgentDeps],
    query: str,
    limit: int = 5,
) -> list[RecipeDescription]:
    """Find recipes in the shared recipe catalog and return their ingredients and preparation steps.

    Use this when the user asks how to prepare a recipe from their recipe book.

    Args:
        query: Words from the recipe name, e.g. "oats" or "chicken curry".
        limit: Maximum number of recipe matches to describe, from 1 to 10.
    """
    recipes = await ctx.deps.repos.recipes.search(
        query,
        limit=max(1, min(limit, 10)),
    )
    return [
        RecipeDescription(
            recipe_id=recipe.id,
            name=recipe.name,
            servings=recipe.servings,
            ingredients=recipe.ingredients,
            preparation_instructions=(
                recipe.preparation_instructions.strip()
                if recipe.preparation_instructions and recipe.preparation_instructions.strip()
                else "No preparation instructions have been saved for this recipe."
            ),
        )
        for recipe in recipes
    ]