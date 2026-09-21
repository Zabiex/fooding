"""Because tools take their dependencies through `ctx.deps`, they can be tested
with a stub context and in-memory fakes — no Gemini call, no Postgres.

    pytest -q
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic_ai import ModelRetry

from calorie_bot.agent.dependencies import AgentDeps
from calorie_bot.agent.tools import create_recipe, get_daily_summary, log_meal
from calorie_bot.domain.models import (
    EntrySource,
    LogEntry,
    LogEntryDraft,
    MealType,
    Nutrition,
    Recipe,
    RecipeDraft,
    UserProfile,
)
from calorie_bot.services import nutrition as nutrition_service

USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")


# =============================================================================
# Fakes
# =============================================================================
class FakeRecipeRepo:
    def __init__(self) -> None:
        self.rows: dict[UUID, Recipe] = {}

    async def save(self, user_id, draft: RecipeDraft, *, overwrite_existing=True):
        existing = next(
            (r for r in self.rows.values() if r.user_id == user_id and r.name == draft.name),
            None,
        )
        now = datetime.now(tz=timezone.utc)
        recipe = Recipe(
            id=existing.id if existing else uuid4(),
            user_id=user_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            **draft.model_dump(),
        )
        self.rows[recipe.id] = recipe
        return recipe, existing is not None

    async def get(self, user_id, recipe_id):
        recipe = self.rows.get(recipe_id)
        # The scoping rule under test: wrong owner -> nothing.
        return recipe if recipe and recipe.user_id == user_id else None

    async def search(self, user_id, query, limit=5):
        return [
            r
            for r in self.rows.values()
            if r.user_id == user_id and query.lower() in r.name.lower()
        ][:limit]


class FakeLogRepo:
    def __init__(self) -> None:
        self.rows: list[LogEntry] = []

    async def create(self, user_id, draft: LogEntryDraft, *, timezone_name="UTC"):
        entry = LogEntry(
            id=uuid4(),
            user_id=user_id,
            recipe_id=draft.recipe_id,
            description=draft.description,
            meal_type=draft.meal_type,
            source=draft.source,
            servings=draft.servings,
            nutrition=draft.nutrition_total,
            confidence=draft.confidence,
            logged_at=draft.logged_at or datetime.now(tz=timezone.utc),
            created_at=datetime.now(tz=timezone.utc),
        )
        self.rows.append(entry)
        return entry

    async def list_for_day(self, user_id, day: date, timezone_name: str):
        return [r for r in self.rows if r.user_id == user_id and r.logged_at.date() == day]


@dataclass
class FakeRepos:
    recipes: FakeRecipeRepo
    log_entries: FakeLogRepo
    users: object = None


def make_ctx(user_id: UUID = USER_A, *, target: int | None = 2000) -> SimpleNamespace:
    user = UserProfile(
        id=user_id,
        telegram_user_id=999,
        first_name="Test",
        timezone="UTC",
        daily_calorie_target=target,
    )
    deps = AgentDeps(
        user=user,
        repos=FakeRepos(FakeRecipeRepo(), FakeLogRepo()),  # type: ignore[arg-type]
        input_source=EntrySource.TEXT,
    )
    return SimpleNamespace(deps=deps)


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_create_recipe_persists_per_serving_values():
    ctx = make_ctx()
    saved = await create_recipe(
        ctx,
        name="Overnight oats",
        calories_per_serving=420,
        servings=2,
        protein_g_per_serving=18,
        carbs_g_per_serving=55,
        fat_g_per_serving=13,
    )
    assert saved.name == "Overnight oats"
    assert saved.nutrition_per_serving.calories == 420
    assert saved.was_updated is False


@pytest.mark.asyncio
async def test_create_recipe_rejects_inconsistent_macros():
    ctx = make_ctx()
    with pytest.raises(ModelRetry):
        await create_recipe(
            ctx,
            name="Impossible salad",
            calories_per_serving=100,   # 90 g of fat is ~810 kcal on its own
            fat_g_per_serving=90,
        )


@pytest.mark.asyncio
async def test_log_meal_scales_by_servings_and_reports_remaining():
    ctx = make_ctx(target=2000)
    logged = await log_meal(
        ctx,
        description="scrambled eggs",
        calories_per_serving=150,
        protein_g_per_serving=13,
        fat_g_per_serving=10,
        servings=2,
        meal_type=MealType.BREAKFAST,
    )
    assert logged.nutrition_logged.calories == 300
    assert logged.day_total_calories == 300
    assert logged.calories_remaining == 1700


@pytest.mark.asyncio
async def test_log_meal_cannot_reach_another_users_recipe():
    ctx = make_ctx(USER_A)
    foreign = Recipe(
        id=uuid4(),
        user_id=USER_B,
        name="Someone else's curry",
        servings=1,
        ingredients=[],
        nutrition_per_serving=Nutrition(calories=600),
        tags=[],
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    ctx.deps.repos.recipes.rows[foreign.id] = foreign

    with pytest.raises(ModelRetry):
        await log_meal(ctx, description="curry", recipe_id=str(foreign.id))


@pytest.mark.asyncio
async def test_daily_summary_groups_by_meal():
    ctx = make_ctx()
    await log_meal(ctx, description="toast", calories_per_serving=200, meal_type=MealType.BREAKFAST)
    await log_meal(ctx, description="soup", calories_per_serving=300, meal_type=MealType.LUNCH)

    summary = await get_daily_summary(ctx, day_offset=0)
    assert summary.totals.calories == 500
    assert summary.entry_count == 2
    assert {b.meal_type for b in summary.by_meal} == {MealType.BREAKFAST, MealType.LUNCH}


@pytest.mark.asyncio
async def test_future_day_offset_is_refused():
    ctx = make_ctx()
    with pytest.raises(ModelRetry):
        await get_daily_summary(ctx, day_offset=1)


def test_macro_consistency_check():
    good = Nutrition(calories=400, protein_g=20, carbs_g=40, fat_g=13)
    bad = Nutrition(calories=100, protein_g=0, carbs_g=0, fat_g=90)
    assert nutrition_service.macros_are_consistent(good)
    assert not nutrition_service.macros_are_consistent(bad)
