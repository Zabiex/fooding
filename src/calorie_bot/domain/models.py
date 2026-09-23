"""Pure data structures.

This module is deliberately dependency-free: no database, no Telegram, no LLM.
Everything above it (repositories, services, agent tools, bot handlers) speaks
these types to everything else.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Enums (mirror the Postgres enum types)
# =============================================================================
class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    DRINK = "drink"
    OTHER = "other"


class EntrySource(str, Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    RECIPE = "recipe"
    MANUAL = "manual"


# =============================================================================
# Value objects
# =============================================================================
class Nutrition(BaseModel):
    """A bundle of macros. Immutable; arithmetic returns new instances."""

    model_config = ConfigDict(frozen=True)

    calories: float = Field(..., ge=0, description="Energy in kilocalories.")
    protein_g: float = Field(0.0, ge=0, description="Protein in grams.")
    carbs_g: float = Field(0.0, ge=0, description="Carbohydrates in grams.")
    fat_g: float = Field(0.0, ge=0, description="Fat in grams.")
    fiber_g: float = Field(0.0, ge=0, description="Fiber in grams.")

    @classmethod
    def zero(cls) -> "Nutrition":
        return cls(calories=0.0)

    def scaled(self, factor: float) -> "Nutrition":
        if factor < 0:
            raise ValueError("Scaling factor must be non-negative.")
        return Nutrition(
            calories=self.calories * factor,
            protein_g=self.protein_g * factor,
            carbs_g=self.carbs_g * factor,
            fat_g=self.fat_g * factor,
            fiber_g=self.fiber_g * factor,
        )

    def __add__(self, other: "Nutrition") -> "Nutrition":
        return Nutrition(
            calories=self.calories + other.calories,
            protein_g=self.protein_g + other.protein_g,
            carbs_g=self.carbs_g + other.carbs_g,
            fat_g=self.fat_g + other.fat_g,
            fiber_g=self.fiber_g + other.fiber_g,
        )

    def rounded(self, digits: int = 1) -> "Nutrition":
        return Nutrition(
            calories=round(self.calories, digits),
            protein_g=round(self.protein_g, digits),
            carbs_g=round(self.carbs_g, digits),
            fat_g=round(self.fat_g, digits),
            fiber_g=round(self.fiber_g, digits),
        )

    @classmethod
    def sum(cls, items: Iterable["Nutrition"]) -> "Nutrition":
        total = cls.zero()
        for item in items:
            total = total + item
        return total


class Ingredient(BaseModel):
    """One line of a recipe. Quantities are optional — free text is allowed."""

    name: str = Field(..., min_length=1, description="Ingredient name, e.g. 'rolled oats'.")
    quantity: float | None = Field(None, ge=0, description="Numeric amount, e.g. 80.")
    unit: str | None = Field(None, description="Unit for the amount, e.g. 'g', 'ml', 'tbsp'.")
    note: str | None = Field(None, description="Preparation note, e.g. 'finely chopped'.")


# =============================================================================
# Recipes
# =============================================================================
class RecipeDraft(BaseModel):
    """A recipe as proposed by the agent, before it is persisted."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    servings: float = Field(1.0, gt=0, description="How many servings the full recipe yields.")
    ingredients: list[Ingredient] = Field(default_factory=list)
    nutrition_per_serving: Nutrition
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Recipe name cannot be blank.")
        return cleaned

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, values: list[str]) -> list[str]:
        return [tag.strip().lower() for tag in values if tag.strip()]

    @property
    def nutrition_total(self) -> Nutrition:
        return self.nutrition_per_serving.scaled(self.servings)


class Recipe(RecipeDraft):
    """A persisted recipe."""

    id: UUID
    user_id: UUID
    is_archived: bool = False
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Log entries
# =============================================================================
class LogEntryDraft(BaseModel):
    """A consumption event as proposed by the agent, before it is persisted."""

    description: str = Field(..., min_length=1, max_length=500)
    meal_type: MealType = MealType.OTHER
    source: EntrySource = EntrySource.TEXT
    servings: float = Field(1.0, gt=0)
    nutrition_per_serving: Nutrition
    recipe_id: UUID | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    raw_input: str | None = None
    logged_at: datetime | None = Field(
        None, description="When the food was eaten. Defaults to now."
    )

    @property
    def nutrition_total(self) -> Nutrition:
        return self.nutrition_per_serving.scaled(self.servings)


class LogEntry(BaseModel):
    """A persisted consumption event. `nutrition` is the total for the entry."""

    id: UUID
    user_id: UUID
    recipe_id: UUID | None
    description: str
    meal_type: MealType
    source: EntrySource
    servings: float
    nutrition: Nutrition
    confidence: float | None
    logged_at: datetime
    created_at: datetime


# =============================================================================
# Users
# =============================================================================
class UserProfile(BaseModel):
    """The authenticated user. Built from the Telegram update, never from the LLM."""

    id: UUID
    telegram_user_id: int
    telegram_chat_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    locale: str = "en"
    timezone: str = "UTC"
    daily_calorie_target: int | None = None
    protein_target_g: float | None = None
    carbs_target_g: float | None = None
    fat_target_g: float | None = None
    whitelist: bool = False
    is_active: bool = True

    @property
    def display_name(self) -> str:
        return self.first_name or self.username or f"user {self.telegram_user_id}"

    @property
    def targets(self) -> Nutrition | None:
        if self.daily_calorie_target is None:
            return None
        return Nutrition(
            calories=float(self.daily_calorie_target),
            protein_g=self.protein_target_g or 0.0,
            carbs_g=self.carbs_target_g or 0.0,
            fat_g=self.fat_target_g or 0.0,
        )


class UserUpsert(BaseModel):
    """What the bot knows about a user straight from a Telegram update."""

    telegram_user_id: int
    telegram_chat_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    locale: str = "en"


class UserTargetsUpdate(BaseModel):
    daily_calorie_target: int | None = Field(None, gt=0)
    protein_target_g: float | None = Field(None, ge=0)
    carbs_target_g: float | None = Field(None, ge=0)
    fat_target_g: float | None = Field(None, ge=0)
    timezone: str | None = None


# =============================================================================
# Reporting
# =============================================================================
class MealBreakdown(BaseModel):
    meal_type: MealType
    nutrition: Nutrition
    entry_count: int


class DailySummary(BaseModel):
    """What `get_daily_summary` hands back to the model and to the bot."""

    day: date
    timezone: str
    totals: Nutrition
    entry_count: int
    by_meal: list[MealBreakdown] = Field(default_factory=list)
    calorie_target: int | None = None
    calories_remaining: float | None = None
    percent_of_target: float | None = None
    entries: list[LogEntry] = Field(default_factory=list)


# =============================================================================
# Tool results — small, explicit payloads returned to the LLM
# =============================================================================
class RecipeSaved(BaseModel):
    recipe_id: UUID
    name: str
    servings: float
    nutrition_per_serving: Nutrition
    was_updated: bool = Field(
        False, description="True when an existing recipe with the same name was overwritten."
    )


class MealLogged(BaseModel):
    entry_id: UUID
    description: str
    meal_type: MealType
    servings: float
    nutrition_logged: Nutrition
    logged_at: datetime
    day_total_calories: float
    calories_remaining: float | None = None


class RecipeMatch(BaseModel):
    recipe_id: UUID
    name: str
    servings: float
    nutrition_per_serving: Nutrition
