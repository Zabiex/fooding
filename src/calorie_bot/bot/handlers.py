"""Telegram handlers.

Responsibilities, and nothing else:
  1. Authenticate — turn `update.effective_user.id` into a `UserProfile` row.
  2. Fetch the bytes of a photo.
  3. Hand off to `AgentRunner` or straight to a repository for commands.
  4. Render the result.

The user identity always comes from the Telegram update, never from message
content, so every database write is scoped to the sender by construction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..agent.runner import AgentError, AgentRunner
from ..db.repositories import Repositories
from ..domain.models import UserProfile, UserTargetsUpdate, UserUpsert
from ..services.nutrition import build_daily_summary
from ..services.timeframes import is_valid_timezone, parse_day_offset
from . import formatting

logger = logging.getLogger(__name__)

BOT_SERVICES_KEY = "services"


@dataclass
class BotServices:
    """Everything the handlers need, parked in `application.bot_data`."""

    repos: Repositories
    runner: AgentRunner
    default_timezone: str


def _services(context: ContextTypes.DEFAULT_TYPE) -> BotServices:
    services = context.application.bot_data[BOT_SERVICES_KEY]
    assert isinstance(services, BotServices)
    return services


async def _current_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> UserProfile:
    """Resolve (and lazily create) the sender's row. This is the auth boundary."""
    telegram_user = update.effective_user
    if telegram_user is None or telegram_user.is_bot:
        raise PermissionError("No human sender on this update.")

    services = _services(context)
    return await services.repos.users.upsert_from_telegram(
        UserUpsert(
            telegram_user_id=telegram_user.id,
            telegram_chat_id=update.effective_chat.id if update.effective_chat else None,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            locale=(telegram_user.language_code or "en")[:5],
        )
    )


async def _reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message is None:
        return
    for chunk in formatting.split_message(text):
        await message.reply_text(
            chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)


# =============================================================================
# Commands
# =============================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _current_user(update, context)
    await _reply(update, formatting.WELCOME)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, formatting.WELCOME)


async def _summary_for_offset(
    update: Update, context: ContextTypes.DEFAULT_TYPE, offset: int
) -> None:
    user = await _current_user(update, context)
    services = _services(context)
    day = parse_day_offset(offset, user.timezone)
    entries = await services.repos.log_entries.list_for_day(user.id, day, user.timezone)
    summary = build_daily_summary(user=user, day=day, entries=entries)
    await _reply(update, formatting.format_daily_summary(summary))


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _summary_for_offset(update, context, 0)


async def yesterday_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _summary_for_offset(update, context, -1)


async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _current_user(update, context)
    services = _services(context)

    if not context.args:
        current = (
            f"Your daily target is <b>{user.daily_calorie_target} kcal</b>."
            if user.daily_calorie_target
            else "You have no daily target set."
        )
        await _reply(update, f"{current}\nSet one with <code>/target 2200</code>.")
        return

    try:
        calories = int(context.args[0])
        if not 500 <= calories <= 10000:
            raise ValueError
    except ValueError:
        await _reply(update, "Please give a whole number of calories, e.g. <code>/target 2200</code>.")
        return

    updated = await services.repos.users.update_targets(
        user.id, UserTargetsUpdate(daily_calorie_target=calories)
    )
    await _reply(update, f"✅ Daily target set to <b>{updated.daily_calorie_target} kcal</b>.")


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _current_user(update, context)
    services = _services(context)

    if not context.args:
        await _reply(
            update,
            f"Your timezone is <b>{formatting.e(user.timezone)}</b>.\n"
            "Change it with <code>/timezone Europe/Helsinki</code>.",
        )
        return

    name = context.args[0]
    if not is_valid_timezone(name):
        await _reply(update, f"I don't recognise <b>{formatting.e(name)}</b>. Use an IANA name like <code>Europe/Helsinki</code>.")
        return

    updated = await services.repos.users.update_targets(user.id, UserTargetsUpdate(timezone=name))
    await _reply(update, f"✅ Timezone set to <b>{formatting.e(updated.timezone)}</b>.")


async def recipes_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _current_user(update, context)
    services = _services(context)
    recipes = await services.repos.recipes.list_recent(limit=25)
    await _reply(update, formatting.format_recipe_list(recipes))


async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _current_user(update, context)
    services = _services(context)
    removed = await services.repos.log_entries.delete_latest(user.id)
    if removed is None:
        await _reply(update, "There's nothing to undo.")
        return
    await _reply(
        update,
        f"🗑 Removed <b>{formatting.e(removed.description)}</b> "
        f"({removed.nutrition.calories:.0f} kcal).",
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _current_user(update, context)
    _services(context).runner.reset(user.telegram_user_id)
    await _reply(update, "🧹 Conversation cleared. Your log and recipes are untouched.")


# =============================================================================
# Text and photos
# =============================================================================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    user = await _current_user(update, context)
    services = _services(context)
    await _typing(update, context)

    try:
        reply = await services.runner.run_text(user, message.text)
    except AgentError as exc:
        await _reply(update, formatting.e(str(exc)))
        return

    await _reply(update, formatting.e(reply.text))


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return

    user = await _current_user(update, context)
    services = _services(context)
    await _typing(update, context)

    # `message.photo` is ascending by resolution; the last item is the largest.
    photo = message.photo[-1]
    telegram_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await telegram_file.download_as_bytearray())

    try:
        reply = await services.runner.run_photo(
            user,
            image_bytes,
            media_type="image/jpeg",  # Telegram always re-encodes photos as JPEG.
            caption=message.caption,
        )
    except AgentError as exc:
        await _reply(update, formatting.e(str(exc)))
        return

    await _reply(update, formatting.e(reply.text))


async def document_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Images sent as files ("send without compression") arrive as documents."""
    message = update.effective_message
    if message is None or message.document is None:
        return

    document = message.document
    mime = document.mime_type or ""
    if not mime.startswith("image/"):
        await _reply(update, "I can only read food photos, not files.")
        return

    user = await _current_user(update, context)
    services = _services(context)
    await _typing(update, context)

    telegram_file = await context.bot.get_file(document.file_id)
    image_bytes = bytes(await telegram_file.download_as_bytearray())

    try:
        reply = await services.runner.run_photo(
            user, image_bytes, media_type=mime, caption=message.caption
        )
    except AgentError as exc:
        await _reply(update, formatting.e(str(exc)))
        return

    await _reply(update, formatting.e(reply.text))


# =============================================================================
# Errors
# =============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong on my side. Please try again in a moment."
            )
        except Exception:  # noqa: BLE001 - never let the error handler raise
            logger.exception("Failed to deliver the error message.")


# =============================================================================
# Registration
# =============================================================================
def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("yesterday", yesterday_command))
    application.add_handler(CommandHandler("target", target_command))
    application.add_handler(CommandHandler("timezone", timezone_command))
    application.add_handler(CommandHandler("recipes", recipes_command))
    application.add_handler(CommandHandler("undo", undo_command))
    application.add_handler(CommandHandler("reset", reset_command))

    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(MessageHandler(filters.Document.IMAGE, document_photo_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    application.add_error_handler(error_handler)
