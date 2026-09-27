"""Return the current user's daily nutrition summary."""

from __future__ import annotations

from pydantic_ai import ModelRetry, RunContext

from ...domain.models import DailySummary
from ...services import nutrition as nutrition_service
from ...services.timeframes import parse_day_offset
from ..dependencies import AgentDeps
from .common import MAX_SUMMARY_ENTRIES


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