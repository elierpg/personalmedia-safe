from asyncio import sleep as asleep
from datetime import datetime, timezone
import secrets

from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from Backend.helper.encrypt import encode_string
from Backend.helper.pyro import get_readable_file_size
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
        name = getattr(file, "file_name", None) or (message.caption or "file")
        return {
            "file_name": name,
            "mime_type": getattr(file, "mime_type", None),
            "file_size": int(getattr(file, "file_size", None) or 0),
        }
    return {
        "file_name": message.caption or "file",
        "mime_type": None,
        "file_size": 0,
    }


def _guess_quality(file_name: str) -> str:
    n = (file_name or "").lower()
    for q in ("2160p", "4k", "1080p", "720p", "480p", "360p"):
        if q in n:
            return "2160p" if q == "4k" else q
    return "HD"


async def index_skip_placeholder(db, skip_chat_id: int, skip_msg_id: int, message: Message, pending_key: str):
    """Index a placeholder media entry pointing to the skip-channel message so it can be assigned later."""
    if db is None:
        return None
    info = _extract_skip_file_info(message)
    file_name = (info.get("file_name") or "Archivo pendiente").strip()
    raw_size = int(info.get("file_size") or 0)
    channel_norm = int(str(skip_chat_id).replace("-100", ""))
    encoded = await encode_string({"chat_id": channel_norm, "msg_id": int(skip_msg_id)})
    quality = _guess_quality(file_name)
    # synthetic negative tmdb_id for pending item
    tmdb_id = -(secrets.randbelow(2_000_000_000 - 10_000) + 10_000)
    imdb_id = f"skip{int(skip_msg_id)}{secrets.randbelow(9999)}"
    metadata_info = {
        "tmdb_id": tmdb_id,
        "imdb_id": imdb_id,
        "title": file_name.rsplit(".", 1)[0] if "." in file_name else file_name,
        "year": 0,
        "rate": 0,
        "description": "Archivo pendiente de asignar metadata (canal de skip).",
        "poster": "",
        "backdrop": "",
        "logo": "",
        "genres": [],
        "cast": [],
        "runtime": "",
        "media_type": "movie",
        "quality": quality,
        "encoded_string": encoded,
        "pending_skip": True,
    }
    try:
        insert_status = {}
        await db.insert_media(
            metadata_info,
            channel=channel_norm,
            msg_id=int(skip_msg_id),
            size=get_readable_file_size(raw_size),
            name=file_name,
            raw_size=raw_size,
            status=insert_status,
        )
        # store placeholder identity in pending record
        await db.dbs["tracking"]["skip_pending"].update_one(
            {"_id": pending_key},
            {"$set": {
                "placeholder_tmdb_id": tmdb_id,
                "placeholder_imdb_id": imdb_id,
                "placeholder_media_type": "movie",
                "placeholder_db_index": getattr(db, "current_db_index", 1),
                "placeholder_title": metadata_info["title"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return {"tmdb_id": tmdb_id, "media_type": "movie", "db_index": getattr(db, "current_db_index", 1)}
    except Exception as e:
        LOGGER.warning(f"[SkipChannel] Could not index placeholder for skip msg {skip_msg_id}: {e}")
        return None


async def record_skip_pending(db, skip_chat_id: int, skip_msg_id: int, message: Message, reason: str = "metadata_failed", index_placeholder: bool = True) -> dict | None:
    if db is None:
        return None
    try:
        info = _extract_skip_file_info(message)
        caption = (message.caption or "").strip()
        pending_key = f"{int(skip_chat_id)}:{int(skip_msg_id)}"
        doc = {
            "_id": pending_key,
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
        placeholder = None
        if index_placeholder:
            placeholder = await index_skip_placeholder(db, int(skip_chat_id), int(skip_msg_id), message, pending_key)
        return {"id": pending_key, "placeholder": placeholder}
    except Exception as e:
        LOGGER.warning(f"[SkipChannel] Could not record pending skip item: {e}")
        return None


async def route_to_skip_channel(client: Client, message: Message, db=None, reason: str = "metadata_failed", index_placeholder: bool = True) -> dict | None:
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
            n = str(skip).strip()
            copied_chat_id = int(n) if n.startswith("-") else int("-100" + n.replace("-100", ""))
        skip_msg_id = getattr(copied, "id", None)
        if copied_chat_id is not None and skip_msg_id is not None:
            rec = await record_skip_pending(db, int(copied_chat_id), int(skip_msg_id), message, reason=reason, index_placeholder=index_placeholder)
            result = {"skip_chat_id": int(copied_chat_id), "skip_msg_id": int(skip_msg_id), "record": rec}

    if settings.delete_on_metadata_fail:
        try:
            from Backend.helper.task_manager import delete_message
            await delete_message(message.chat.id, message.id)
        except Exception as e:
            LOGGER.warning(f"[SkipChannel] Could not delete original message {message.id}: {e}")

    return result
