"""Return details for saved exercises."""

from __future__ import annotations

from pydantic_ai import RunContext

from ...domain.models import ExerciseDescription
from ..dependencies import AgentDeps


async def describe_exercise(
    ctx: RunContext[AgentDeps],
    query: str,
    limit: int = 5,
) -> list[ExerciseDescription]:
    """Find exercises in the user's saved catalog and return their details.

    Use this when the user asks how to perform a saved exercise.

    Args:
        query: Words from the exercise name, e.g. "squat" or "deadlift".
        limit: Maximum number of exercise matches to describe, from 1 to 10.
    """
    exercises = await ctx.deps.repos.exercises.search(
        query,
        limit=max(1, min(limit, 10)),
    )
    return [
        ExerciseDescription(
            exercise_id=exercise.exercise_id,
            name=exercise.name,
            description=(
                exercise.description.strip()
                if exercise.description and exercise.description.strip()
                else "No description has been saved for this exercise."
            ),
            tips=(
                exercise.tips.strip()
                if exercise.tips and exercise.tips.strip()
                else None
            ),
            muscle_groups=exercise.muscle_groups,
        )
        for exercise in exercises
    ]
