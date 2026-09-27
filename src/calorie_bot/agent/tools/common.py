"""Shared validation and limits for agent tools."""

from pydantic_ai import ModelRetry

from ...domain.models import Nutrition
from ...services import nutrition as nutrition_service

MAX_SUMMARY_ENTRIES = 30


def validate_macros(nutrition: Nutrition, label: str) -> None:
    """Bounce obviously inconsistent estimates back to the model."""
    if not nutrition_service.macros_are_consistent(nutrition):
        derived = nutrition_service.implied_calories(nutrition)
        raise ModelRetry(
            f"The macros for {label} do not match the calories: "
            f"{nutrition.protein_g:g} g protein + {nutrition.carbs_g:g} g carbs + "
            f"{nutrition.fat_g:g} g fat imply about {derived:.0f} kcal, but you said "
            f"{nutrition.calories:.0f} kcal. Recheck using 4/4/9 kcal per gram and call the tool again."
        )