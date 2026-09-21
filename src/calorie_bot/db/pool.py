"""Database connector: owns the asyncpg pool and nothing else."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from ..config import Settings

logger = logging.getLogger(__name__)


async def _init_connection(connection: asyncpg.Connection) -> None:
    """Make jsonb columns round-trip as Python objects instead of strings."""
    for type_name in ("json", "jsonb"):
        await connection.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def create_pool(settings: Settings) -> asyncpg.Pool:
    """Open the connection pool.

    `statement_cache_size=0` is required when pointing at Supabase's transaction
    pooler (port 6543), which multiplexes connections and therefore cannot keep
    server-side prepared statements. It is harmless on a direct connection.
    """
    if settings.database_url:
        dsn = settings.database_url.get_secret_value()
        pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=settings.db_min_pool_size,
            max_size=settings.db_max_pool_size,
            command_timeout=settings.db_command_timeout,
            statement_cache_size=settings.db_statement_cache_size,
            init=_init_connection,
        )
    else:
        # Build pool from individual parameters. asyncpg accepts these kwargs
        # directly which avoids DSN parsing issues with special characters.
        # If we're running in development and the user didn't provide DB_HOST
        # fall back to sensible local defaults so developers can run a local
        # Postgres instance without changing production env vars.
        is_dev = settings.app_env.lower().startswith("dev") if getattr(settings, "app_env", None) else False
        host = settings.db_host or ("127.0.0.1" if is_dev else None)
        port = settings.db_port or (5432 if is_dev else None)
        database = settings.db_name or ("fooding_dev" if is_dev else None)
        user = settings.db_user or ("postgres" if is_dev else None)
        password = settings.db_password.get_secret_value() if settings.db_password else None

        if not (host and user and database):
            raise RuntimeError(
                "Database configuration not provided. Set DATABASE_URL or DB_HOST/DB_USER/DB_NAME (or set APP_ENV=development to use local defaults)."
            )

        pool = await asyncpg.create_pool(
            user=user,
            password=password,
            database=database,
            host=host,
            port=port,
            min_size=settings.db_min_pool_size,
            max_size=settings.db_max_pool_size,
            command_timeout=settings.db_command_timeout,
            statement_cache_size=settings.db_statement_cache_size,
            init=_init_connection,
        )
    if pool is None:  # pragma: no cover - asyncpg only returns None on misuse
        raise RuntimeError("Failed to create the database pool.")
    logger.info("Database pool ready (max_size=%s).", settings.db_max_pool_size)
    return pool


@asynccontextmanager
async def pool_lifespan(settings: Settings) -> AsyncIterator[asyncpg.Pool]:
    pool = await create_pool(settings)
    try:
        yield pool
    finally:
        await pool.close()
        logger.info("Database pool closed.")
