"""Composition root: builds the pool, repositories, agent, runner and bot."""

from __future__ import annotations

import asyncio
import logging

from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder, Defaults
from telegram.constants import ParseMode

from ..agent.history import ConversationStore
from ..agent.nutrition_agent import build_agent
from ..agent.runner import AgentRunner
from ..config import Settings, get_settings
from ..db.pool import create_pool
from ..db.repositories import Repositories
from ..db.schema import initialize_schema
from .handlers import BOT_SERVICES_KEY, BotServices, register_handlers

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("today", "Today's food log"),
    BotCommand("yesterday", "Yesterday's food log"),
    BotCommand("recipes", "Your saved recipes"),
    BotCommand("target", "Set your daily calorie goal"),
    BotCommand("timezone", "Set your timezone"),
    BotCommand("undo", "Remove the last entry"),
    BotCommand("reset", "Clear the conversation"),
    BotCommand("help", "How to use this bot"),
]

_POOL_KEY = "db_pool"


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or get_settings()

    async def post_init(application: Application) -> None:
        logger.info("post_init: starting application initialization")
        try:
            # Fail fast if DB pool creation blocks (e.g. network issues).
            pool = await asyncio.wait_for(create_pool(settings), timeout=15)
        except asyncio.TimeoutError:
            logger.exception("Timed out while creating database pool in post_init")
            raise
        except Exception:
            logger.exception("Failed to create database pool in post_init")
            raise

        application.bot_data[_POOL_KEY] = pool

        if settings.run_schema_init_on_startup:
            logger.info("post_init: initializing DB schema")
            await initialize_schema(pool)

        repos = Repositories.from_pool(pool)
        runner = AgentRunner(
            agent=build_agent(settings),
            repos=repos,
            settings=settings,
            history=ConversationStore(
                max_turns=settings.history_turns_kept,
                ttl_seconds=settings.history_ttl_seconds,
            ),
        )
        application.bot_data[BOT_SERVICES_KEY] = BotServices(
            repos=repos,
            runner=runner,
            default_timezone=settings.default_timezone,
        )

        logger.info("post_init: services populated in bot_data")

        await application.bot.set_my_commands(BOT_COMMANDS)
        me = await application.bot.get_me()
        logger.info("Bot @%s is up.", me.username)

    async def post_shutdown(application: Application) -> None:
        pool = application.bot_data.get(_POOL_KEY)
        if pool is not None:
            await pool.close()
            logger.info("Database pool closed.")

    return (
        ApplicationBuilder()
        .token(settings.telegram_bot_token.get_secret_value())
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        # Users are independent; don't serialise everyone behind one slow photo.
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )


def run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    application = build_application(settings)
    register_handlers(application)
    application.run_polling(drop_pending_updates=True)
