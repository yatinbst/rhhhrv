import html

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import database as db
from utils import safe_answer, user_message
from bot.keyboards import settings_menu
from bot.states import SettingsStates

router = Router()


def _settings_text(user: dict) -> str:
    return (
        "⚙️ SETTINGS\n\n"
        f"🔔 Notifications: {'ON' if user['notifications'] else 'OFF'}\n"
        f"☁️ Default Drive: {html.escape(str(user['default_drive']))}\n"
        f"📁 Default Folder: {html.escape(str(user['default_folder_name']))}\n"
        f"🌐 Language: {html.escape(str(user['language']))}"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    user = db.get_user(message.from_user.id)
    await message.answer(_settings_text(user), reply_markup=settings_menu())


@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(call: CallbackQuery):
    await cmd_settings(user_message(call))
    await safe_answer(call)


@router.callback_query(F.data == "settings:notifications")
async def cb_toggle_notifications(call: CallbackQuery):
    user = db.get_user(call.from_user.id)
    new_val = 0 if user["notifications"] else 1
    db.update_user_field(call.from_user.id, "notifications", new_val)
    user = db.get_user(call.from_user.id)
    await call.message.edit_text(_settings_text(user), reply_markup=settings_menu())
    await safe_answer(call, f"Notifications {'ON' if new_val else 'OFF'}")


@router.callback_query(F.data == "settings:default_drive")
async def cb_default_drive(call: CallbackQuery):
    # Single-drive (My Drive) support for now; toggled/confirmed here.
    db.update_user_field(call.from_user.id, "default_drive", "My Drive")
    user = db.get_user(call.from_user.id)
    await call.message.edit_text(_settings_text(user), reply_markup=settings_menu())
    await safe_answer(call, "Default drive set to My Drive")


@router.callback_query(F.data == "settings:default_folder")
async def cb_default_folder(call: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsStates.waiting_default_folder)
    await call.message.answer("📁 Send the name for your default upload folder.")
    await safe_answer(call)


@router.message(SettingsStates.waiting_default_folder)
async def receive_default_folder(message: Message, state: FSMContext):
    await state.clear()
    name = message.text.strip()
    db.update_user_field(message.from_user.id, "default_folder_name", name)
    db.update_user_field(message.from_user.id, "default_folder_id", None)  # re-resolve/create on next upload
    await message.answer(f"✅ Default folder set to: {html.escape(name)}")


@router.callback_query(F.data == "settings:language")
async def cb_language(call: CallbackQuery):
    db.update_user_field(call.from_user.id, "language", "English")
    user = db.get_user(call.from_user.id)
    await call.message.edit_text(_settings_text(user), reply_markup=settings_menu())
    await safe_answer(call, "Language set to English")


@router.message(Command("notifications"))
async def cmd_notifications(message: Message, command: CommandObject):
    user = db.get_user(message.from_user.id) or {}
    if command.args and command.args.lower() in ("on", "off"):
        val = 1 if command.args.lower() == "on" else 0
        db.update_user_field(message.from_user.id, "notifications", val)
        await message.answer(f"🔔 Notifications turned {'ON' if val else 'OFF'}.")
    else:
        await message.answer(f"🔔 Notifications currently: {'ON' if user.get('notifications', 1) else 'OFF'}\nUsage: /notifications on|off")


@router.message(Command("language"))
async def cmd_language(message: Message, command: CommandObject):
    if command.args:
        db.update_user_field(message.from_user.id, "language", command.args.strip())
        await message.answer(f"🌐 Language set to: {html.escape(command.args.strip())}")
    else:
        user = db.get_user(message.from_user.id) or {}
        language = html.escape(str(user.get("language", "English")))
        await message.answer(f"🌐 Current language: {language}\nUsage: /language <name>")


@router.message(Command("timezone"))
async def cmd_timezone(message: Message, command: CommandObject):
    if command.args:
        db.update_user_field(message.from_user.id, "timezone", command.args.strip())
        await message.answer(f"🕒 Timezone set to: {html.escape(command.args.strip())}")
    else:
        user = db.get_user(message.from_user.id) or {}
        timezone = html.escape(str(user.get("timezone", "UTC")))
        await message.answer(f"🕒 Current timezone: {timezone}\nUsage: /timezone <tz>")


@router.message(Command("defaultfolder"))
async def cmd_defaultfolder(message: Message, command: CommandObject):
    if command.args:
        db.update_user_field(message.from_user.id, "default_folder_name", command.args.strip())
        db.update_user_field(message.from_user.id, "default_folder_id", None)
        await message.answer(f"📁 Default folder set to: {html.escape(command.args.strip())}")
    else:
        user = db.get_user(message.from_user.id) or {}
        folder_name = html.escape(str(user.get("default_folder_name", "Gdrive HR")))
        await message.answer(f"📁 Current default folder: {folder_name}\nUsage: /defaultfolder <name>")


@router.message(Command("defaultdrive"))
async def cmd_defaultdrive(message: Message):
    db.update_user_field(message.from_user.id, "default_drive", "My Drive")
    await message.answer("☁️ Default drive set to: My Drive")
