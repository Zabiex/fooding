"""Save an exercise to the current user's exercise catalog."""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from ...domain.models import ExerciseDraft, ExerciseSaved
from ..dependencies import AgentDeps

logger = logging.getLogger(__name__)


async def create_exercise(
    ctx: RunContext[AgentDeps],
    name: str,
    description: str | None = None,
    tips: str | None = None,
    muscle_groups: list[str] | None = None,
    overwrite_existing: bool = True,
) -> ExerciseSaved:
    """Save an exercise to this user's personal exercise catalog.

    Use this when the user describes a movement they want to remember so they can
    log it later by name without re-describing it.

    Args:
        name: Short exercise name, e.g. "Barbell squat" or "Walking lunges".
        description: Optional explanation of the movement or setup.
        tips: Optional technique tips or cues.
        muscle_groups: Optional list of targeted muscle groups.
        overwrite_existing: Replace an exercise of the same name if one exists.
    """
    draft = ExerciseDraft(
        name=name,
        description=description,
        tips=tips,
        muscle_groups=muscle_groups or [],
    )

    exercise, was_updated = await ctx.deps.repos.exercises.save(
        ctx.deps.user_id,
        draft,
        overwrite_existing=overwrite_existing,
    )
    logger.info(
        "exercise_saved user=%s exercise=%s updated=%s",
        ctx.deps.user.telegram_user_id,
        exercise.exercise_id,
        was_updated,
    )
    return ExerciseSaved(
        exercise_id=exercise.exercise_id,
        name=exercise.name,
        description=exercise.description,
        tips=exercise.tips,
        muscle_groups=exercise.muscle_groups,
        was_updated=was_updated,
    )
