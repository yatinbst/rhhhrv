import asyncio
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

import database as db
from utils import is_admin, safe_answer


async def _reply(event: TelegramObject, text: str) -> None:
    """Send a text reply appropriate for the event type.

    FIX #8: hasattr(event, "answer") is unreliable — both Message and
    CallbackQuery have an .answer() method but with completely different
    semantics (new chat message vs. popup notification).  Use explicit
    isinstance checks so the user always sees a proper chat message.
    """
    if isinstance(event, Message):
        await event.answer(text)
    elif isinstance(event, CallbackQuery):
        # send a proper chat message via the underlying message, then
        # acknowledge the callback so the spinner on the button clears.
        if event.message:
            await event.message.answer(text)
        await safe_answer(event)


class GateMiddleware(BaseMiddleware):
    """Blocks banned users, and respects global bot on/off + maintenance mode.
    Admins always pass through so they can run /bot_on, /bot_off, etc.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,  # Message or CallbackQuery (not raw Update)
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        if is_admin(user.id):
            return await handler(event, data)

        db_user = await asyncio.to_thread(db.get_user, user.id)
        if db_user and db_user.get("is_banned"):
            return  # silently drop

        bot_enabled = await asyncio.to_thread(db.get_state, "bot_enabled")
        if bot_enabled == "0":
            await _reply(event, "🔴 The bot is currently disabled by the admin. Please try again later.")
            return

        maintenance = await asyncio.to_thread(db.get_state, "maintenance")
        if maintenance == "1":
            await _reply(event, "🛠️ The bot is under maintenance. Please try again shortly.")
            return

        return await handler(event, data)


class CallbackAckMiddleware(BaseMiddleware):
    """Clear Telegram's button spinner before slow handler work starts."""

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            await safe_answer(event)
        return await handler(event, data)
