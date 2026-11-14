from asyncio import sleep as asleep
from datetime import datetime, timezone

from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from Backend.helper.settings_manager import SettingsManager
from Backend.logger import LOGGER


def is_skip_channel(message: Message) -> bool:
    skip = SettingsManager.current().skip_channel
    if not skip:
        return False
    ref = str(skip).strip()
    if ref.lstrip("@-").replace("-100", "").isdigit():
        return ref.replace("-100", "").lstrip("@") == str(message.chat.id).replace("-100", "")
    username = (getattr(message.chat, "username", None) or "").lower()
    return bool(username) and ref.lstrip("@").lower() == username


def _extract_skip_file_info(message: Message) -> dict:
    file = message.video or message.document
    if file:
        return {
            "file_name": getattr(file, "file_name", None) or (message.caption or "file"),
            "mime_type": getattr(file, "mime_type", None),
            "file_size": getattr(file, "file_size", None) or 0,
        }
    return {
        "file_name": message.caption or "file",
        "mime_type": None,
        "file_size": 0,
    }


async def record_skip_pending(db, skip_chat_id: int, skip_msg_id: int, message: Message, reason: str = "metadata_failed") -> None:
    if db is None:
        return
    try:
        info = _extract_skip_file_info(message)
        caption = (message.caption or "").strip()
        doc = {
            "_id": f"{int(skip_chat_id)}:{int(skip_msg_id)}",
            "skip_chat_id": int(skip_chat_id),
            "skip_msg_id": int(skip_msg_id),
            "source_chat_id": int(message.chat.id),
            "source_msg_id": int(message.id),
            "file_name": info.get("file_name"),
            "caption": caption[:2000] if caption else None,
            "file_size": int(info.get("file_size") or 0),
            "mime_type": info.get("mime_type"),
            "reason": reason,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.dbs["tracking"]["skip_pending"].update_one(
            {"_id": doc["_id"]},
            {"$set": doc},
            upsert=True,
        )
    except Exception as e:
        LOGGER.warning(f"[SkipChannel] Could not record pending skip item: {e}")


async def route_to_skip_channel(client: Client, message: Message, db=None, reason: str = "metadata_failed") -> dict | None:
    settings = SettingsManager.current()
    skip = settings.skip_channel
    if not skip:
        return None

    skip_chat = int(skip) if str(skip).lstrip("-").replace("-100", "").isdigit() else skip

    copied = None
    try:
        copied = await message.copy(skip_chat)
    except FloodWait as e:
        await asleep(e.value)
        try:
            copied = await message.copy(skip_chat)
        except Exception as e2:
            LOGGER.error(f"[SkipChannel] Copy failed for message {message.id}: {e2}")
            return None
    except Exception as e:
        LOGGER.error(f"[SkipChannel] Could not copy message {message.id} to skip channel: {e}")
        return None

    result = None
    if copied is not None:
        copied_chat_id = getattr(getattr(copied, "chat", None), "id", None) or (int(skip_chat) if str(skip_chat).lstrip("-").isdigit() else None)
        if copied_chat_id is None and str(skip).lstrip("-").replace("-100", "").isdigit():
            # normalize to full chat id if numeric
            n = str(skip).strip()
            copied_chat_id = int(n) if n.startswith("-") else int("-100" + n.replace("-100", ""))
        skip_msg_id = getattr(copied, "id", None)
        if copied_chat_id is not None and skip_msg_id is not None:
            await record_skip_pending(db, int(copied_chat_id), int(skip_msg_id), message, reason=reason)
            result = {"skip_chat_id": int(copied_chat_id), "skip_msg_id": int(skip_msg_id)}

    if settings.delete_on_metadata_fail:
        try:
            from Backend.helper.task_manager import delete_message
            await delete_message(message.chat.id, message.id)
        except Exception as e:
            LOGGER.warning(f"[SkipChannel] Could not delete original message {message.id}: {e}")

    return result
