"""Schema bootstrap.

`schema.sql` defines `public.initialize_nutrition_schema()` and calls it. This
module ships that file to the server, which makes startup idempotent: existing
deployments are untouched, fresh ones get the full schema.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

SCHEMA_SQL_PATH = Path(__file__).with_name("schema.sql")

# Advisory lock id so two bot replicas starting at once don't race on DDL.
_SCHEMA_LOCK_ID = 0x0CA1_0713


def read_schema_sql() -> str:
    return SCHEMA_SQL_PATH.read_text(encoding="utf-8")


async def initialize_schema(pool: asyncpg.Pool) -> None:
    """Create types, tables, indexes, triggers and policies if absent."""
    sql = read_schema_sql()
    async with pool.acquire() as connection:
        await connection.execute("select pg_advisory_lock($1)", _SCHEMA_LOCK_ID)
        try:
            await connection.execute(sql)
            logger.info("Schema initialized (or already current).")
        finally:
            await connection.execute("select pg_advisory_unlock($1)", _SCHEMA_LOCK_ID)


async def run_initializer_only(pool: asyncpg.Pool) -> None:
    """Call the stored function without re-shipping the DDL file.

    Useful once `schema.sql` has been applied via a migration tool and you only
    want to re-run the idempotent body.
    """
    async with pool.acquire() as connection:
        await connection.execute("select public.initialize_nutrition_schema()")
