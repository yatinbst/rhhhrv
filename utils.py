from config import cfg


def is_admin(user_id: int) -> bool:
    return user_id in cfg.ADMIN_IDS


def user_message(call):
    """Many callback handlers reuse a /command handler by calling it with
    `call.message`. But `call.message` is the message the BOT sent (the one
    with the inline keyboard on it) - its `.from_user` is the bot itself, not
    the person who tapped the button. Any handler that reads
    `message.from_user.id` off that object silently operates as the bot
    (writing bot rows into the users table, sending Google's OAuth `state` as
    the bot's own Telegram ID, etc.), which is what eventually causes
    Telegram to reject a later send with "Forbidden: bot can't send messages
    to bot".

    This returns a copy of `call.message` with `.from_user` corrected to
    `call.from_user` (the real, clicking user), so it's safe to pass into
    those handlers.
    """
    return call.message.model_copy(deep=True, update={"from_user": call.from_user})


def human_bytes(n: int | float | None) -> str:
    if not n:
        return "0 B"
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def progress_bar(done: int, total: int, width: int = 12) -> str:
    if total <= 0:
        return "░" * width + " 0%"
    pct = min(done / total, 1.0)
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled) + f" {int(pct * 100)}%"
