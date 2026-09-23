"""Data access.

Every method that touches user-owned rows takes `user_id` as its first argument
and puts it in the WHERE clause. That is the tenant boundary: there is no query
in this file capable of returning another user's data, so an agent tool can't
leak one even if the model is talked into trying.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone as dt_timezone
from typing import Any, Sequence
from uuid import UUID

import asyncpg

from ..domain.models import (
    EntrySource,
    Ingredient,
    LogEntry,
    LogEntryDraft,
    MealType,
    Nutrition,
    Recipe,
    RecipeDraft,
    UserProfile,
    UserTargetsUpdate,
    UserUpsert,
)
from ..services.timeframes import day_bounds_utc, to_utc

Row = asyncpg.Record


# =============================================================================
# Row -> model mappers
# =============================================================================
def _nutrition_from_row(row: Row) -> Nutrition:
    return Nutrition(
        calories=row["calories"],
        protein_g=row["protein_g"],
        carbs_g=row["carbs_g"],
        fat_g=row["fat_g"],
        fiber_g=row["fiber_g"],
    )


def _user_from_row(row: Row) -> UserProfile:
    return UserProfile(
        id=row["id"],
        telegram_user_id=row["telegram_user_id"],
        telegram_chat_id=row["telegram_chat_id"],
        username=row["username"],
        first_name=row["first_name"],
        locale=row["locale"],
        timezone=row["timezone"],
        daily_calorie_target=row["daily_calorie_target"],
        protein_target_g=row["protein_target_g"],
        carbs_target_g=row["carbs_target_g"],
        fat_target_g=row["fat_target_g"],
        whitelist=row["whitelist"],
        is_active=row["is_active"],
    )


def _recipe_from_row(row: Row) -> Recipe:
    raw_ingredients: Sequence[dict[str, Any]] = row["ingredients"] or []
    return Recipe(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        description=row["description"],
        servings=row["servings"],
        ingredients=[Ingredient.model_validate(item) for item in raw_ingredients],
        nutrition_per_serving=_nutrition_from_row(row),
        tags=list(row["tags"] or []),
        is_archived=row["is_archived"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _log_entry_from_row(row: Row) -> LogEntry:
    return LogEntry(
        id=row["id"],
        user_id=row["user_id"],
        recipe_id=row["recipe_id"],
        description=row["description"],
        meal_type=MealType(row["meal_type"]),
        source=EntrySource(row["source"]),
        servings=row["servings"],
        nutrition=_nutrition_from_row(row),
        confidence=row["confidence"],
        logged_at=row["logged_at"],
        created_at=row["created_at"],
    )


_RECIPE_COLUMNS = """
    id, user_id, name, description, servings, ingredients,
    calories, protein_g, carbs_g, fat_g, fiber_g,
    tags, is_archived, created_at, updated_at
"""

_LOG_COLUMNS = """
    id, user_id, recipe_id, description, meal_type, source, servings,
    calories, protein_g, carbs_g, fat_g, fiber_g,
    confidence, logged_at, created_at
"""


# =============================================================================
# Users
# =============================================================================
class UserRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_from_telegram(self, payload: UserUpsert) -> UserProfile:
        """Create the user on first contact, refresh their Telegram metadata after."""
        row = await self._pool.fetchrow(
            """
            insert into public.users
                (telegram_user_id, telegram_chat_id, username, first_name, locale, whitelist)
            values ($1, $2, $3, $4, $5, false)
            on conflict (telegram_user_id) do update
                set telegram_chat_id = coalesce(excluded.telegram_chat_id, public.users.telegram_chat_id),
                    username         = coalesce(excluded.username,         public.users.username),
                    first_name       = coalesce(excluded.first_name,       public.users.first_name),
                    locale           = excluded.locale
            returning *
            """,
            payload.telegram_user_id,
            payload.telegram_chat_id,
            payload.username,
            payload.first_name,
            payload.locale,
        )
        assert row is not None
        return _user_from_row(row)

    async def get_by_telegram_id(self, telegram_user_id: int) -> UserProfile | None:
        row = await self._pool.fetchrow(
            "select * from public.users where telegram_user_id = $1",
            telegram_user_id,
        )
        return _user_from_row(row) if row else None

    async def update_targets(self, user_id: UUID, patch: UserTargetsUpdate) -> UserProfile:
        row = await self._pool.fetchrow(
            """
            update public.users
               set daily_calorie_target = coalesce($2, daily_calorie_target),
                   protein_target_g     = coalesce($3, protein_target_g),
                   carbs_target_g       = coalesce($4, carbs_target_g),
                   fat_target_g         = coalesce($5, fat_target_g),
                   timezone             = coalesce($6, timezone)
             where id = $1
            returning *
            """,
            user_id,
            patch.daily_calorie_target,
            patch.protein_target_g,
            patch.carbs_target_g,
            patch.fat_target_g,
            patch.timezone,
        )
        if row is None:
            raise LookupError(f"User {user_id} does not exist.")
        return _user_from_row(row)

    async def clear_daily_calorie_target(self, user_id: UUID) -> UserProfile:
        row = await self._pool.fetchrow(
            """
            update public.users
               set daily_calorie_target = null
             where id = $1
            returning *
            """,
            user_id,
        )
        if row is None:
            raise LookupError(f"User {user_id} does not exist.")
        return _user_from_row(row)


# =============================================================================
# Recipes
# =============================================================================
class RecipeRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(
        self,
        user_id: UUID,
        draft: RecipeDraft,
        *,
        overwrite_existing: bool = True,
    ) -> tuple[Recipe, bool]:
        """Insert a recipe, or update the user's existing one with the same name.

        Returns `(recipe, was_updated)`.
        """
        ingredients = [item.model_dump(exclude_none=True) for item in draft.ingredients]
        nutrition = draft.nutrition_per_serving

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                existing = await connection.fetchrow(
                    """
                    select id from public.recipes
                     where user_id = $1 and lower(btrim(name)) = lower(btrim($2))
                     for update
                    """,
                    user_id,
                    draft.name,
                )

                if existing and not overwrite_existing:
                    row = await connection.fetchrow(
                        f"select {_RECIPE_COLUMNS} from public.recipes where id = $1 and user_id = $2",
                        existing["id"],
                        user_id,
                    )
                    assert row is not None
                    return _recipe_from_row(row), False

                if existing:
                    row = await connection.fetchrow(
                        f"""
                        update public.recipes
                           set name = $3, description = $4, servings = $5, ingredients = $6,
                               calories = $7, protein_g = $8, carbs_g = $9, fat_g = $10, fiber_g = $11,
                               tags = $12, is_archived = false
                         where id = $1 and user_id = $2
                        returning {_RECIPE_COLUMNS}
                        """,
                        existing["id"],
                        user_id,
                        draft.name,
                        draft.description,
                        draft.servings,
                        ingredients,
                        nutrition.calories,
                        nutrition.protein_g,
                        nutrition.carbs_g,
                        nutrition.fat_g,
                        nutrition.fiber_g,
                        draft.tags,
                    )
                    assert row is not None
                    return _recipe_from_row(row), True

                row = await connection.fetchrow(
                    f"""
                    insert into public.recipes
                        (user_id, name, description, servings, ingredients,
                         calories, protein_g, carbs_g, fat_g, fiber_g, tags)
                    values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    returning {_RECIPE_COLUMNS}
                    """,
                    user_id,
                    draft.name,
                    draft.description,
                    draft.servings,
                    ingredients,
                    nutrition.calories,
                    nutrition.protein_g,
                    nutrition.carbs_g,
                    nutrition.fat_g,
                    nutrition.fiber_g,
                    draft.tags,
                )
                assert row is not None
                return _recipe_from_row(row), False

    async def get(self, recipe_id: UUID) -> Recipe | None:
        row = await self._pool.fetchrow(
            f"select {_RECIPE_COLUMNS} from public.recipes where id = $1",
            recipe_id,
        )
        return _recipe_from_row(row) if row else None

    async def get_by_name(self, name: str) -> Recipe | None:
        row = await self._pool.fetchrow(
            f"""
            select {_RECIPE_COLUMNS} from public.recipes
             where lower(btrim(name)) = lower(btrim($1))
            """,
            name,
        )
        return _recipe_from_row(row) if row else None

    async def search(self, query: str, limit: int = 5) -> list[Recipe]:
        """Trigram-similarity search across all recipes (not scoped to a user)."""
        rows = await self._pool.fetch(
            f"""
            select {_RECIPE_COLUMNS}
              from public.recipes
             where is_archived = false
               and (name ilike '%' || $1 || '%' or similarity(name, $1) > 0.2)
             order by similarity(name, $1) desc, updated_at desc
             limit $2
            """,
            query,
            limit,
        )
        return [_recipe_from_row(row) for row in rows]

    async def list_recent(self, limit: int = 20) -> list[Recipe]:
        rows = await self._pool.fetch(
            f"""
            select {_RECIPE_COLUMNS} from public.recipes
             where is_archived = false
             order by updated_at desc
             limit $1
            """,
            limit,
        )
        return [_recipe_from_row(row) for row in rows]

    async def archive(self, user_id: UUID, recipe_id: UUID) -> bool:
        result = await self._pool.execute(
            "update public.recipes set is_archived = true where id = $1 and user_id = $2",
            recipe_id,
            user_id,
        )
        return result.endswith("1")


# =============================================================================
# Log entries
# =============================================================================
class LogEntryRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        user_id: UUID,
        draft: LogEntryDraft,
        *,
        timezone_name: str = "UTC",
    ) -> LogEntry:
        total = draft.nutrition_total
        logged_at = (
            to_utc(draft.logged_at, timezone_name)
            if draft.logged_at is not None
            else datetime.now(tz=dt_timezone.utc)
        )

        row = await self._pool.fetchrow(
            f"""
            insert into public.log_entries
                (user_id, recipe_id, description, meal_type, source, servings,
                 calories, protein_g, carbs_g, fat_g, fiber_g,
                 confidence, raw_input, logged_at)
            values ($1, $2, $3, $4::public.meal_type, $5::public.entry_source, $6,
                    $7, $8, $9, $10, $11, $12, $13, $14)
            returning {_LOG_COLUMNS}
            """,
            user_id,
            draft.recipe_id,
            draft.description,
            draft.meal_type.value,
            draft.source.value,
            draft.servings,
            total.calories,
            total.protein_g,
            total.carbs_g,
            total.fat_g,
            total.fiber_g,
            draft.confidence,
            draft.raw_input,
            logged_at,
        )
        assert row is not None
        return _log_entry_from_row(row)

    async def list_for_day(
        self,
        user_id: UUID,
        day: date,
        timezone_name: str,
    ) -> list[LogEntry]:
        start_utc, end_utc = day_bounds_utc(day, timezone_name)
        rows = await self._pool.fetch(
            f"""
            select {_LOG_COLUMNS} from public.log_entries
             where user_id = $1 and logged_at >= $2 and logged_at < $3
             order by logged_at asc
            """,
            user_id,
            start_utc,
            end_utc,
        )
        return [_log_entry_from_row(row) for row in rows]

    async def list_recent(self, user_id: UUID, limit: int = 10) -> list[LogEntry]:
        rows = await self._pool.fetch(
            f"""
            select {_LOG_COLUMNS} from public.log_entries
             where user_id = $1
             order by logged_at desc
             limit $2
            """,
            user_id,
            limit,
        )
        return [_log_entry_from_row(row) for row in rows]

    async def delete(self, user_id: UUID, entry_id: UUID) -> bool:
        result = await self._pool.execute(
            "delete from public.log_entries where id = $1 and user_id = $2",
            entry_id,
            user_id,
        )
        return result.endswith("1")

    async def delete_latest(self, user_id: UUID) -> LogEntry | None:
        row = await self._pool.fetchrow(
            f"""
            delete from public.log_entries
             where id = (
                 select id from public.log_entries
                  where user_id = $1
                  order by created_at desc
                  limit 1
             )
            returning {_LOG_COLUMNS}
            """,
            user_id,
        )
        return _log_entry_from_row(row) if row else None


# =============================================================================
# Container passed around as a single dependency
# =============================================================================
@dataclass(frozen=True)
class Repositories:
    users: UserRepository
    recipes: RecipeRepository
    log_entries: LogEntryRepository

    @classmethod
    def from_pool(cls, pool: asyncpg.Pool) -> "Repositories":
        return cls(
            users=UserRepository(pool),
            recipes=RecipeRepository(pool),
            log_entries=LogEntryRepository(pool),
        )
