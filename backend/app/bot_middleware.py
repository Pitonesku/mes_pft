"""
Telegram Bot Middleware — Database-backed authentication for aiogram 3.x.
Checks that the incoming user's Telegram ID exists in the PostgreSQL users table
and injects the user object + role into the handler context data.
"""

import os
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from sqlalchemy.orm import Session

import importlib
if __package__:
    models = importlib.import_module(f"{__package__}.models")
else:
    import models


class DbAuthMiddleware(BaseMiddleware):
    """
    Intercepts every incoming Message and CallbackQuery.
    Looks up the user in PostgreSQL by Telegram ID.
    - If NOT found → replies with an access-denied message and aborts (CancelHandler).
    - If found → injects ``data["db_user"]`` (dict with id, username, role)
      and ``data["user_role"]`` (str) for downstream handlers.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Only apply to Message and CallbackQuery updates
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        # --- Maintenance mode: block interactive commands, keep report worker running ---
        if os.getenv("BOT_MAINTENANCE_MODE", "").lower() == "true":
            maint_text = "🔧 Bot is under maintenance. Please try later."
            if isinstance(event, Message):
                await event.answer(maint_text)
            elif isinstance(event, CallbackQuery):
                await event.answer(maint_text, show_alert=True)
            return  # block all interactive handlers

        deny_text = (
            "🚫 Access denied. "
            "Your Telegram ID ({tg_id}) is not registered in the production system."
        )

        tg_user = event.from_user
        if tg_user is None:
            # No Telegram user attached to this update — deny and block execution
            no_id_text = (
                "🚫 Access denied. "
                "Your Telegram ID is not registered in the production system."
            )
            if isinstance(event, Message):
                await event.answer(no_id_text)
            elif isinstance(event, CallbackQuery):
                await event.answer(no_id_text, show_alert=True)
            # Abort: do NOT call the handler
            return

        db: Session = self.session_factory()
        try:
            user = db.query(models.User).filter(
                models.User.telegram_id == tg_user.id
            ).first()

            if user is None:
                # Access denied — reply with TG ID and abort execution
                formatted_deny = deny_text.format(tg_id=tg_user.id)
                if isinstance(event, Message):
                    await event.answer(formatted_deny)
                elif isinstance(event, CallbackQuery):
                    await event.answer(formatted_deny, show_alert=True)
                # Abort: do NOT call the handler
                return

            # Inject user info into handler context
            tg_role = user.tg_role or "user"
            data["db_user"] = {
                "id": user.id,
                "username": user.username,
                "role": tg_role,
                "telegram_id": user.telegram_id,
            }
            data["user_role"] = tg_role

            return await handler(event, data)
        finally:
            db.close()
