#!/usr/bin/env python3
"""Quick async test to verify the `DATABASE_URL` can authenticate with asyncpg.

Usage:
  # ensure .env is loaded or DATABASE_URL is exported
  uv run python scripts/test_db_connection.py
"""
import asyncio
import os
import traceback
from pathlib import Path


def load_env_file_if_missing():
    """Load project .env into os.environ if DATABASE_URL is not already set.

    This is intentionally simple: it supports lines like KEY=VALUE and strips
    surrounding quotes. Comments and blank lines are ignored.
    """
    if os.environ.get("DATABASE_URL"):
        return
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        # remove surrounding single/double quotes
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ): 
            val = val[1:-1]
        # only set if not already in environment
        if key not in os.environ:
            os.environ[key] = val

try:
    import asyncpg
except Exception:
    print("asyncpg not installed. Install with: pip install asyncpg")
    raise


async def main():
    dsn = os.environ.get("DATABASE_URL")
    try:
        if dsn:
            conn = await asyncpg.connect(dsn)
        else:
            host = os.environ.get("DB_HOST")
            port = os.environ.get("DB_PORT")
            database = os.environ.get("DB_NAME")
            user = os.environ.get("DB_USER")
            password = os.environ.get("DB_PASSWORD")
            if not (host and user and password and database):
                print("DATABASE_URL not set in environment. Export it or provide DB_HOST/DB_USER/DB_PASSWORD/DB_NAME in the environment or .env file.")
                return
            conn = await asyncpg.connect(
                host=host, port=int(port) if port else None, database=database, user=user, password=password
            )
        print("Connected to database successfully.")
        await conn.close()
    except Exception:
        print("Connection failed:")
        traceback.print_exc()


if __name__ == "__main__":
    load_env_file_if_missing()
    asyncio.run(main())
