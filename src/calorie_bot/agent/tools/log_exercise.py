"""Log an exercise entry with estimated calories burned."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from ...domain.models import ExerciseEntry, ExerciseEntryDraft
from ..dependencies import AgentDeps

logger = logging.getLogger(__name__)


async def log_exercise(
    ctx: RunContext[AgentDeps],
    name: str,
    duration_seconds: float = 0.0,
    reps: int | None = None,
    sets: int | None = None,
    weight: float | None = None,
    calories_burned: float = 0.0,
    exercise_id: str | None = None,
    hours_ago: float = 0.0,
) -> ExerciseEntry:
    """Log an exercise entry into the user's exercise log.

    Args:
        name: The name of the exercise performed, e.g. "running", "yoga", "cycling".
        duration_seconds: How long the exercise lasted in seconds.
        reps: Number of repetitions, if applicable.
        sets: Number of sets, if applicable.
        calories_burned: Estimated calories burned for the entire exercise.
        hours_ago: How long ago the exercise was performed. 0 means now; 3 means three hours ago.
    """
    deps = ctx.deps
    resolved_exercise_id: UUID | None = None

    if exercise_id:
        try:
            resolved_exercise_id = UUID(exercise_id)
        except ValueError as exc:
            raise ModelRetry(
                f"'{exercise_id}' is not a valid exercise id. Call describe_exercise to get a real one, "
                "or omit it and log the exercise by name."
            ) from exc

        exercise = await deps.repos.exercises.get(resolved_exercise_id)
        if exercise is None:
            raise ModelRetry(
                f"Exercise with id '{exercise_id}' does not exist. Call describe_exercise first, or log a new exercise."
            )

    if reps is not None and reps <= 0:
        raise ModelRetry("reps must be greater than zero when provided.")

    if sets is not None and sets <= 0:
        raise ModelRetry("sets must be greater than zero when provided.")

    if weight is not None and weight < 0:
        raise ModelRetry("weight cannot be negative.")

    if duration_seconds <= 0:
        raise ModelRetry("duration_seconds must be greater than zero.")

    if calories_burned < 0:
        raise ModelRetry("calories_burned cannot be negative.")

    logged_at = deps.now_local() - timedelta(hours=max(0.0, hours_ago))
    draft_entry = ExerciseEntryDraft(
        user=deps.user_id,
        exercise_id=resolved_exercise_id,
        duration_seconds=duration_seconds,
        reps=reps,
        sets=sets,
        weight=weight,
        calories_burned=calories_burned,
        logged_at=logged_at,
    )

    entry = await deps.repos.exercise_entries.create(
        deps.user_id, draft_entry, timezone_name=deps.timezone
    )

    logger.info(
        "exercise_logged user=%s entry=%s kcal=%.0f",
        deps.user.telegram_user_id,
        entry.entry_id,
        entry.calories_burned,
    )
    return entry