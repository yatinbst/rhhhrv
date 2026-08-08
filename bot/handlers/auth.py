from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

import database as db
import google_auth
import drive_service
from utils import human_bytes, safe_answer, user_message
from bot.keyboards import login_keyboard, logout_confirm

router = Router()


@router.message(Command("login"))
async def cmd_login(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    user = db.get_user(message.from_user.id)
    if user and user.get("google_token"):
        await message.answer("✅ You're already connected to Google Drive. Use /logout first to switch accounts.")
        return
    auth_url = google_auth.build_auth_url(state=str(message.from_user.id))
    text = (
        "☁️ Google Drive Login\n\n"
        "Connect your Google Drive account to start uploading and cloning files."
    )
    await message.answer(text, reply_markup=login_keyboard(auth_url))


@router.callback_query(F.data == "auth:login")
async def cb_login(call: CallbackQuery):
    # NOTE: must use user_message(call), not call.message - call.message was
    # sent by the bot, so its from_user is the bot itself. Passing it
    # straight through here used to leak into build_auth_url(state=...),
    # meaning Google's OAuth "state" carried the bot's own Telegram ID, and
    # the callback later tried bot.send_message(<bot's own id>, ...), which
    # Telegram rejects with "Forbidden: bot can't send messages to bot".
    await cmd_login(user_message(call))
    await safe_answer(call)


@router.message(Command("logout"))
async def cmd_logout(message: Message):
    user = db.get_user(message.from_user.id)
    if not user or not user.get("google_token"):
        await message.answer("You're not connected to any Google Drive account.")
        return
    text = (
        "⚠️ Logout Confirmation\n\n"
        f"You're currently connected to:\n{user['google_email']}\n\n"
        "Logging out will disconnect this Google Drive account from the bot."
    )
    await message.answer(text, reply_markup=logout_confirm())


@router.callback_query(F.data == "auth:logout_confirm")
async def cb_logout_confirm(call: CallbackQuery):
    db.clear_google_token(call.from_user.id)
    db.log_action(call.from_user.id, "logout")
    await call.message.edit_text("✅ Logged out. Your Google Drive account has been disconnected.")
    await safe_answer(call)


@router.callback_query(F.data == "auth:logout_cancel")
async def cb_logout_cancel(call: CallbackQuery):
    await call.message.edit_text("Logout cancelled.")
    await safe_answer(call)


async def cmd_me(message: Message, override_user_id: int | None = None):
    user_id = override_user_id or message.from_user.id
    user = db.get_user(user_id)
    if not user or not user.get("google_token"):
        await message.answer("☁️ Not connected. Use /login to connect your Google Drive account.")
        return

    import json
    token = json.loads(user["google_token"])
    try:
        about = drive_service.get_about(token)
    except Exception as e:
        await message.answer(f"⚠️ Couldn't fetch Drive info: {e}\nTry /login again.")
        return

    used = about["usage_bytes"]
    limit = about["limit_bytes"]
    pct = f"{(used / limit * 100):.0f}%" if limit else "n/a"
    available = human_bytes(limit - used) if limit else "∞"

    text = (
        "👤 MY DRIVE INFO\n\n"
        "Telegram\n"
        f"├── ID: {user_id}\n"
        f"├── Username: @{user['username'] or 'n/a'}\n"
        f"└── Plan: {'⭐ Premium' if user['is_premium'] else '🆓 Free'}\n\n"
        "☁️ Google Drive\n"
        f"├── Account: {about['email']}\n"
        "├── Status: 🟢 Connected\n"
        f"├── Storage: {human_bytes(used)} / {human_bytes(limit) if limit else '∞'}\n"
        f"├── Used: {pct}\n"
        f"└── Available: {available}\n\n"
        "📊 Bot Usage\n"
        f"├── Uploads: {user['uploads_count']}\n"
        f"├── Clones: {user['clones_count']}\n"
        f"├── Uploaded: {human_bytes(user['uploaded_bytes'])}\n"
        f"└── Cloned: {human_bytes(user['cloned_bytes'])}"
    )
    await message.answer(text)


@router.message(Command("me"))
async def cmd_me_handler(message: Message):
    await cmd_me(message)
