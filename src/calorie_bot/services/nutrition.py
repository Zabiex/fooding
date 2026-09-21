"""Nutrition business logic. Pure functions over domain models — no IO here,
which makes every rule in this file trivially unit-testable.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..domain.models import (
    DailySummary,
    LogEntry,
    MealBreakdown,
    MealType,
    Nutrition,
    Recipe,
    UserProfile,
)

# Calories implied by one gram of each macro, used for sanity checking.
KCAL_PER_G = {"protein_g": 4.0, "carbs_g": 4.0, "fat_g": 9.0}

# Above this relative gap we consider the macro/calorie pair inconsistent.
MACRO_TOLERANCE = 0.35


def portion_from_recipe(recipe: Recipe, servings: float) -> Nutrition:
    """Nutrition actually consumed when eating `servings` of a stored recipe."""
    return recipe.nutrition_per_serving.scaled(servings)


def implied_calories(nutrition: Nutrition) -> float:
    return sum(getattr(nutrition, field) * factor for field, factor in KCAL_PER_G.items())


def macros_are_consistent(nutrition: Nutrition, tolerance: float = MACRO_TOLERANCE) -> bool:
    """True when the stated calories roughly match 4/4/9 of the stated macros.

    Used to nudge the model into fixing its own arithmetic rather than silently
    persisting a 200 kcal meal that contains 90 g of fat.
    """
    if nutrition.calories <= 0:
        return implied_calories(nutrition) <= 0
    derived = implied_calories(nutrition)
    if derived == 0:
        return True  # Macros were simply not estimated.
    return abs(derived - nutrition.calories) / nutrition.calories <= tolerance


def group_by_meal(entries: list[LogEntry]) -> list[MealBreakdown]:
    buckets: dict[MealType, list[Nutrition]] = defaultdict(list)
    for entry in entries:
        buckets[entry.meal_type].append(entry.nutrition)

    order = list(MealType)
    return [
        MealBreakdown(
            meal_type=meal,
            nutrition=Nutrition.sum(buckets[meal]).rounded(),
            entry_count=len(buckets[meal]),
        )
        for meal in order
        if buckets[meal]
    ]


def build_daily_summary(
    *,
    user: UserProfile,
    day: date,
    entries: list[LogEntry],
    include_entries: bool = True,
) -> DailySummary:
    totals = Nutrition.sum(entry.nutrition for entry in entries).rounded()

    remaining: float | None = None
    percent: float | None = None
    if user.daily_calorie_target:
        remaining = round(user.daily_calorie_target - totals.calories, 1)
        percent = round(100 * totals.calories / user.daily_calorie_target, 1)

    return DailySummary(
        day=day,
        timezone=user.timezone,
        totals=totals,
        entry_count=len(entries),
        by_meal=group_by_meal(entries),
        calorie_target=user.daily_calorie_target,
        calories_remaining=remaining,
        percent_of_target=percent,
        entries=entries if include_entries else [],
    )


def progress_bar(percent: float | None, width: int = 10) -> str:
    """A tiny text gauge for the Telegram reply."""
    if percent is None:
        return ""
    filled = max(0, min(width, round(width * percent / 100)))
    return "█" * filled + "░" * (width - filled)
