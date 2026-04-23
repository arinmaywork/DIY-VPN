"""Telegram allowlist. Only user IDs in TG_ALLOWED_USERS may use the bot."""

import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes


def _allowed_ids() -> set[int]:
    raw = os.environ.get("TG_ALLOWED_USERS", "").strip()
    if not raw:
        return set()
    out = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk:
            try:
                out.add(int(chunk))
            except ValueError:
                pass
    return out


ALLOWED = _allowed_ids()


def authed(handler):
    """Decorator: drops messages from non-allowlisted Telegram users."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in ALLOWED:
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"Not authorized. Your Telegram ID: `{user.id if user else '?'}`. "
                    f"Add it to TG_ALLOWED_USERS and redeploy the bot.",
                    parse_mode="Markdown",
                )
            return
        return await handler(update, context)

    return wrapper
