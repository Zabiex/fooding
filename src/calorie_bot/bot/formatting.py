"""Rendering domain objects into Telegram HTML. Presentation only."""

from __future__ import annotations

from html import escape

from ..domain.models import DailySummary, LogEntry, Recipe
from ..services.nutrition import progress_bar
from ..services.timeframes import to_local

TELEGRAM_MAX_CHARS = 4096
_SAFE_CHUNK = 3800

MEAL_EMOJI = {
    "breakfast": "🍳",
    "lunch": "🥗",
    "dinner": "🍽",
    "snack": "🍎",
    "drink": "🥤",
    "other": "🍴",
}


def e(value: object) -> str:
    return escape(str(value), quote=False)


def split_message(text: str) -> list[str]:
    """Telegram rejects messages over 4096 characters; split on paragraph breaks."""
    if len(text) <= TELEGRAM_MAX_CHARS:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > _SAFE_CHUNK:
        split_at = remaining.rfind("\n", 0, _SAFE_CHUNK)
        if split_at == -1:
            split_at = _SAFE_CHUNK
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def format_entry_line(entry: LogEntry, timezone_name: str) -> str:
    local_time = to_local(entry.logged_at, timezone_name).strftime("%H:%M")
    emoji = MEAL_EMOJI.get(entry.meal_type.value, "🍴")
    servings = f" ×{entry.servings:g}" if entry.servings != 1 else ""
    return (
        f"{emoji} <code>{local_time}</code> {e(entry.description)}{servings} — "
        f"<b>{entry.nutrition.calories:.0f}</b> kcal"
    )


def format_daily_summary(summary: DailySummary, *, title: str | None = None) -> str:
    totals = summary.totals
    heading = title or f"📅 <b>{summary.day.strftime('%A %d %B')}</b>"
    lines = [heading, ""]

    if summary.entry_count == 0:
        lines.append("<i>Nothing logged yet.</i>")
        return "\n".join(lines)

    for entry in summary.entries:
        lines.append(format_entry_line(entry, summary.timezone))

    lines.append("")
    lines.append(f"<b>Total: {totals.calories:.0f} kcal</b>")
    lines.append(
        f"P {totals.protein_g:.0f} g · C {totals.carbs_g:.0f} g · "
        f"F {totals.fat_g:.0f} g · Fib {totals.fiber_g:.0f} g"
    )

    if summary.calorie_target:
        bar = progress_bar(summary.percent_of_target)
        remaining = summary.calories_remaining or 0
        verdict = (
            f"{remaining:.0f} kcal left"
            if remaining >= 0
            else f"{abs(remaining):.0f} kcal over"
        )
        lines.append("")
        lines.append(
            f"{bar} {summary.percent_of_target:.0f}% of {summary.calorie_target} kcal — {verdict}"
        )

    return "\n".join(lines)


def format_recipe_list(recipes: list[Recipe]) -> str:
    if not recipes:
        return "You haven't saved any recipes yet. Describe a dish and I'll store it."
    lines = ["📖 <b>Your recipes</b>", ""]
    for recipe in recipes:
        lines.append(
            f"• <b>{e(recipe.name)}</b> — {recipe.nutrition_per_serving.calories:.0f} kcal/serving "
            f"({recipe.servings:g} servings)"
        )
    return "\n".join(lines)


WELCOME = (
    "👋 <b>Hi! I'm your food diary.</b>\n\n"
    "Just tell me what you ate, or send a photo of your plate:\n"
    "• <i>two eggs and a slice of rye toast</i>\n"
    "• <i>big bowl of chicken curry with rice</i>\n"
    "• 📷 a picture of your lunch\n\n"
    "I'll estimate the calories and macros and keep the running total for your day.\n\n"
    "<b>Commands</b>\n"
    "/today — today's log\n"
    "/yesterday — yesterday's log\n"
    "/target 2200 — set a daily calorie goal (or /target off to clear it)\n"
    "/timezone Europe/Helsinki — set your timezone\n"
    "/recipes — your saved recipes\n"
    "/undo — remove the last entry\n"
    "/reset — forget the current conversation\n\n"
    "<i>Estimates are approximate and not medical advice.</i>"
)
