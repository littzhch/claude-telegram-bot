import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

from claude_telegram_bot import config

logger = logging.getLogger(__name__)


def _load_allowed_ids() -> set[int]:
    """Reload allowed user IDs from config (supports runtime admin changes)."""
    return set(config.ALLOWED_USER_IDS)


def is_allowed(user_id: int) -> bool:
    allowed = _load_allowed_ids()
    return user_id in allowed


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_USER_ID


def require_auth(func):
    """Decorator: reject users not in the allowed list."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_allowed(user_id):
            logger.warning("Unauthorized access from user %s", user_id)
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def require_admin(func):
    """Decorator: reject non-admin users."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            if update.message:
                await update.message.reply_text("Admin only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper
