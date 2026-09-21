"""Apply the schema without starting the bot:  python scripts/init_db.py"""

import asyncio
import logging

from calorie_bot.config import get_settings
from calorie_bot.db.pool import pool_lifespan
from calorie_bot.db.schema import initialize_schema


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    async with pool_lifespan(settings) as pool:
        await initialize_schema(pool)
        print("Schema is up to date.")


if __name__ == "__main__":
    asyncio.run(main())
