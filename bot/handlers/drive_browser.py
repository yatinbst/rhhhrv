import json

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import database as db
import drive_service
from utils import human_bytes, user_message
from bot.keyboards import drive_browser, file_actions, delete_confirm, share_menu
from bot.states import DriveStates

router = Router()

FOLDER_MIME = "application/vnd.google-apps.folder"


async def _ensure_connected(message: Message) -> dict | None:
    user = db.get_user(message.from_user.id)
    if not user or not user.get("google_token"):
        await message.answer("☁️ Connect your Google Drive first with /login.")
        return None
    return user


async def _show_folder(message: Message, token: dict, folder_id: str, state: FSMContext, edit=False):
    data = await state.get_data()
    stack = data.get("stack", [])
    parent_id = stack[-1] if stack else None

    items = drive_service.list_children(token, folder_id)
    text = "☁️ MY DRIVE\n\n" + (f"{len(items)} item(s) here." if items else "This folder is empty.")
    kb = drive_browser(items, folder_id, parent_id)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb)


@router.message(Command("drive"))
async def cmd_drive(message: Message, state: FSMContext):
    user = await _ensure_connected(message)
    if not user:
        return
    await state.set_state(DriveStates.browsing)
    await state.update_data(stack=[], current="root")
    token = json.loads(user["google_token"])
    await _show_folder(message, token, "root", state)


@router.callback_query(F.data == "menu:drive")
async def cb_menu_drive(call: CallbackQuery, state: FSMContext):
    await cmd_drive(user_message(call), state)
    await call.answer()


@router.callback_query(F.data.startswith("drive:open:"))
async def cb_drive_open(call: CallbackQuery, state: FSMContext):
    target_id = call.data.split(":")[-1]
    token = db.get_google_token(call.from_user.id)
    if not token:
        await call.answer("☁️ Connect your Google Drive first with /login.", show_alert=True)
        return

    meta = drive_service.get_file_meta(token, target_id)
    if meta["mimeType"] == FOLDER_MIME:
        data = await state.get_data()
        stack = data.get("stack", [])
        current = data.get("current", "root")
        # Determine direction: if target is the previous stack top, we're going back
        if stack and target_id == stack[-1]:
            stack = stack[:-1]
        else:
            stack.append(current)
        await state.update_data(stack=stack, current=target_id)
        await _show_folder(call.message, token, target_id, state, edit=True)
    else:
        size = human_bytes(int(meta.get("size", 0) or 0))
        await call.message.answer(f"📄 {meta['name']}\n💾 {size}", reply_markup=file_actions(target_id))
    await call.answer()


@router.callback_query(F.data.startswith("drive:mkdir:"))
async def cb_drive_mkdir(call: CallbackQuery, state: FSMContext):
    folder_id = call.data.split(":")[-1]
    await state.set_state(DriveStates.waiting_mkdir_name)
    await state.update_data(mkdir_parent=folder_id)
    await call.message.answer("📁 Send the name for the new folder.")
    await call.answer()


@router.message(DriveStates.waiting_mkdir_name)
async def receive_mkdir_name(message: Message, state: FSMContext):
    data = await state.get_data()
    parent_id = data.get("mkdir_parent", "root")
    await state.set_state(DriveStates.browsing)
    user = await _ensure_connected(message)
    if not user:
        return
    token = json.loads(user["google_token"])
    created = drive_service.mkdir(token, message.text.strip(), parent_id)
    db.log_action(message.from_user.id, "mkdir", created["name"])
    await message.answer(f"✅ Folder created: {created['name']}")
    await _show_folder(message, token, parent_id, state)


@router.message(Command("mkdir"))
async def cmd_mkdir(message: Message, command: CommandObject):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /mkdir <folder name>")
        return
    token = json.loads(user["google_token"])
    parent_id = user.get("default_folder_id") or "root"
    created = drive_service.mkdir(token, command.args.strip(), parent_id)
    db.log_action(message.from_user.id, "mkdir", created["name"])
    await message.answer(f"✅ Folder created: {created['name']}")


@router.message(Command("files"))
async def cmd_files(message: Message):
    user = await _ensure_connected(message)
    if not user:
        return
    token = json.loads(user["google_token"])
    items = drive_service.list_children(token, "root", files_only=True)
    if not items:
        await message.answer("📄 No files found in root.")
        return
    lines = [f"📄 {f['name']} — {human_bytes(int(f.get('size', 0) or 0))}" for f in items[:50]]
    await message.answer("📄 MY FILES\n\n" + "\n".join(lines))


@router.message(Command("folders"))
async def cmd_folders(message: Message):
    user = await _ensure_connected(message)
    if not user:
        return
    token = json.loads(user["google_token"])
    items = drive_service.list_children(token, "root", folders_only=True)
    if not items:
        await message.answer("📁 No folders found in root.")
        return
    lines = [f"📁 {f['name']}" for f in items[:50]]
    await message.answer("📁 MY FOLDERS\n\n" + "\n".join(lines))


# ---------- rename / move / copy / delete / link (triggered from file_actions keyboard) ----------

@router.callback_query(F.data.startswith("drive:rename:"))
async def cb_rename_start(call: CallbackQuery, state: FSMContext):
    file_id = call.data.split(":")[-1]
    await state.set_state(DriveStates.waiting_rename)
    await state.update_data(rename_id=file_id)
    await call.message.answer("✏️ Send the new name.")
    await call.answer()


@router.message(DriveStates.waiting_rename)
async def receive_rename(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("rename_id")
    await state.clear()
    user = await _ensure_connected(message)
    if not user:
        return
    token = json.loads(user["google_token"])
    result = drive_service.rename(token, file_id, message.text.strip())
    db.log_action(message.from_user.id, "rename", result["name"])
    await message.answer(f"✅ Renamed to: {result['name']}")


@router.callback_query(F.data.startswith("drive:move:"))
async def cb_move_start(call: CallbackQuery, state: FSMContext):
    file_id = call.data.split(":")[-1]
    await state.set_state(DriveStates.waiting_move_target)
    await state.update_data(move_id=file_id)
    await call.message.answer("➡️ Send the destination folder link/ID.")
    await call.answer()


@router.message(DriveStates.waiting_move_target)
async def receive_move_target(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("move_id")
    await state.clear()
    user = await _ensure_connected(message)
    if not user:
        return
    target = drive_service.extract_id_from_link((message.text or "").strip())
    if not target:
        await message.answer("❌ Invalid folder link/ID.")
        return
    token = json.loads(user["google_token"])
    drive_service.move(token, file_id, target)
    db.log_action(message.from_user.id, "move", file_id)
    await message.answer("✅ Moved successfully.")


@router.callback_query(F.data.startswith("drive:copy:"))
async def cb_copy_start(call: CallbackQuery, state: FSMContext):
    file_id = call.data.split(":")[-1]
    await state.set_state(DriveStates.waiting_copy_target)
    await state.update_data(copy_id=file_id)
    await call.message.answer("📋 Send the destination folder link/ID (or send /cancel to copy in place).")
    await call.answer()


@router.message(DriveStates.waiting_copy_target)
async def receive_copy_target(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("copy_id")
    await state.clear()
    user = await _ensure_connected(message)
    if not user:
        return
    target = drive_service.extract_id_from_link((message.text or "").strip())
    token = json.loads(user["google_token"])
    result = drive_service.copy(token, file_id, new_parent_id=target)
    db.log_action(message.from_user.id, "copy", result["name"])
    await message.answer(f"✅ Copied: {result['name']}")


@router.callback_query(F.data.startswith("drive:delete_confirm:"))
async def cb_delete_confirm(call: CallbackQuery):
    file_id = call.data.split(":")[-1]
    await call.message.answer("🗑️ Are you sure you want to delete this?", reply_markup=delete_confirm(file_id))
    await call.answer()


@router.callback_query(F.data.startswith("drive:delete:"))
async def cb_delete(call: CallbackQuery):
    file_id = call.data.split(":")[-1]
    token = db.get_google_token(call.from_user.id)
    if not token:
        await call.answer("☁️ Connect your Google Drive first with /login.", show_alert=True)
        return
    drive_service.delete(token, file_id)
    db.log_action(call.from_user.id, "delete", file_id)
    await call.message.edit_text("✅ Deleted.")
    await call.answer()


@router.callback_query(F.data.startswith("drive:cancel:"))
async def cb_drive_cancel(call: CallbackQuery):
    await call.message.edit_text("Cancelled.")
    await call.answer()


@router.callback_query(F.data.startswith("drive:link:"))
async def cb_link(call: CallbackQuery):
    file_id = call.data.split(":")[-1]
    token = db.get_google_token(call.from_user.id)
    if not token:
        await call.answer("☁️ Connect your Google Drive first with /login.", show_alert=True)
        return
    link = drive_service.get_link(token, file_id)
    db.log_action(call.from_user.id, "link", file_id)
    await call.message.answer(f"🔗 {link}")
    await call.answer()


def _share_text(name: str, status: dict) -> str:
    if status["access"] == "anyone":
        role_label = drive_service.ROLE_LABELS.get(status["role"], status["role"])
        access_line = f"🌐 Anyone with the link — {role_label}"
    else:
        access_line = "🔒 Restricted — only people added can open"
    return f"🔒 SHARING SETTINGS\n\n📄 {name}\n\nAccess: {access_line}"


@router.callback_query(F.data.startswith("drive:share:"))
async def cb_share_menu(call: CallbackQuery):
    file_id = call.data.split(":")[-1]
    token = db.get_google_token(call.from_user.id)
    if not token:
        await call.answer("☁️ Connect your Google Drive first with /login.", show_alert=True)
        return
    meta = drive_service.get_file_meta(token, file_id)
    status = drive_service.get_sharing_status(token, file_id)
    await call.message.answer(_share_text(meta["name"], status), reply_markup=share_menu(file_id, status))
    await call.answer()


@router.callback_query(F.data.startswith("drive:share_type:"))
async def cb_share_type(call: CallbackQuery):
    _, _, access, file_id = call.data.split(":")
    token = db.get_google_token(call.from_user.id)
    if not token:
        await call.answer("☁️ Connect your Google Drive first with /login.", show_alert=True)
        return

    if access == "anyone":
        status = drive_service.set_anyone_permission(token, file_id)
    else:
        status = drive_service.set_restricted(token, file_id)

    meta = drive_service.get_file_meta(token, file_id)
    db.log_action(call.from_user.id, "share", f"{file_id}:{access}")
    await call.message.edit_text(_share_text(meta["name"], status), reply_markup=share_menu(file_id, status))
    await call.answer(f"Access set to {'Anyone with link' if access == 'anyone' else 'Restricted'}")


@router.callback_query(F.data.startswith("drive:share_role:"))
async def cb_share_role(call: CallbackQuery):
    _, _, role, file_id = call.data.split(":")
    token = db.get_google_token(call.from_user.id)
    if not token:
        await call.answer("☁️ Connect your Google Drive first with /login.", show_alert=True)
        return

    status = drive_service.set_anyone_permission(token, file_id, role=role)
    meta = drive_service.get_file_meta(token, file_id)
    db.log_action(call.from_user.id, "share_role", f"{file_id}:{role}")
    await call.message.edit_text(_share_text(meta["name"], status), reply_markup=share_menu(file_id, status))
    await call.answer(f"Role set to {drive_service.ROLE_LABELS.get(role, role)}")


@router.message(Command("link"))
async def cmd_link(message: Message, command: CommandObject):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /link <file link or ID>")
        return
    file_id = drive_service.extract_id_from_link(command.args.strip())
    if not file_id:
        await message.answer("❌ Couldn't parse that as a Drive link/ID.")
        return
    token = json.loads(user["google_token"])
    link = drive_service.get_link(token, file_id)
    await message.answer(f"🔗 {link}")


@router.message(Command("rename"))
async def cmd_rename(message: Message, command: CommandObject, state: FSMContext):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /rename <file link or ID>\nThen send the new name when asked.")
        return
    file_id = drive_service.extract_id_from_link(command.args.strip())
    if not file_id:
        await message.answer("❌ Couldn't parse that as a Drive link/ID.")
        return
    await state.set_state(DriveStates.waiting_rename)
    await state.update_data(rename_id=file_id)
    await message.answer("✏️ Send the new name.")


@router.message(Command("move"))
async def cmd_move(message: Message, command: CommandObject, state: FSMContext):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /move <file link or ID>\nThen send the destination folder when asked.")
        return
    file_id = drive_service.extract_id_from_link(command.args.strip())
    if not file_id:
        await message.answer("❌ Couldn't parse that as a Drive link/ID.")
        return
    await state.set_state(DriveStates.waiting_move_target)
    await state.update_data(move_id=file_id)
    await message.answer("➡️ Send the destination folder link/ID.")


@router.message(Command("copy"))
async def cmd_copy(message: Message, command: CommandObject, state: FSMContext):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /copy <file link or ID>\nThen send the destination folder when asked.")
        return
    file_id = drive_service.extract_id_from_link(command.args.strip())
    if not file_id:
        await message.answer("❌ Couldn't parse that as a Drive link/ID.")
        return
    await state.set_state(DriveStates.waiting_copy_target)
    await state.update_data(copy_id=file_id)
    await message.answer("📋 Send the destination folder link/ID (or /cancel to copy in place).")


@router.message(Command("delete"))
async def cmd_delete(message: Message, command: CommandObject):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /delete <file link or ID>")
        return
    file_id = drive_service.extract_id_from_link(command.args.strip())
    if not file_id:
        await message.answer("❌ Couldn't parse that as a Drive link/ID.")
        return
    await message.answer("🗑️ Are you sure you want to delete this?", reply_markup=delete_confirm(file_id))


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject):
    user = await _ensure_connected(message)
    if not user:
        return
    if not command.args:
        await message.answer("Usage: /search <query>")
        return
    token = json.loads(user["google_token"])
    drive = drive_service.get_drive(token)
    query = command.args.replace("'", "\\'")
    results = drive.files().list(
        q=f"name contains '{query}' and trashed = false",
        fields="files(id, name, mimeType, size)",
        pageSize=20,
    ).execute().get("files", [])
    if not results:
        await message.answer(f"🔍 No results for '{command.args}'.")
        return
    lines = []
    for f in results:
        icon = "📁" if f["mimeType"] == FOLDER_MIME else "📄"
        lines.append(f"{icon} {f['name']}")
    await message.answer(f"🔍 SEARCH RESULTS for '{command.args}'\n\n" + "\n".join(lines))


@router.callback_query(F.data == "menu:search")
async def cb_menu_search(call: CallbackQuery):
    await call.message.answer("🔍 Use: /search <query>")
    await call.answer()
