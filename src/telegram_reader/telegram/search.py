from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .dialogs import display_name, type_name


def _iso(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def media_metadata(message: Any) -> tuple[str | None, str | None, dict[str, Any]]:
    for kind in ("photo", "voice", "video", "document", "audio", "animation", "sticker"):
        media = getattr(message, kind, None)
        if media is None:
            continue
        name = getattr(media, "file_name", None)
        metadata = {
            "filename": name,
            "duration": getattr(media, "duration", None),
            "caption": getattr(message, "caption", None),
        }
        return kind, name, {key: value for key, value in metadata.items() if value is not None}
    return None, None, {}


def is_real_private_incoming(message: Any, self_id: int | None = None) -> bool:
    chat = getattr(message, "chat", None)
    sender = getattr(message, "from_user", None)
    return bool(
        chat is not None
        and type_name(chat) == "private"
        and sender is not None
        and not bool(getattr(sender, "is_bot", False))
        and not bool(getattr(message, "outgoing", False))
        and getattr(message, "service", None) is None
        and (self_id is None or int(chat.id) != int(self_id))
    )


def message_record(message: Any, read_inbox_max_id: int = 0) -> dict[str, Any]:
    chat = message.chat
    media_type, media_name, metadata = media_metadata(message)
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    edit_date = getattr(message, "edit_date", None)
    raw_payload = {
        "peer_id": int(chat.id), "message_id": int(message.id), "date": _iso(message.date),
        "edit_date": _iso(edit_date) if edit_date else None, "text": text,
        "media_type": media_type, "media_name": media_name, "media_metadata": metadata,
    }
    raw_hash = hashlib.sha256(
        json.dumps(raw_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        **raw_payload,
        "direction": "outgoing" if bool(getattr(message, "outgoing", False)) else "incoming",
        "telegram_unread": (
            not bool(getattr(message, "outgoing", False)) and int(message.id) > int(read_inbox_max_id)
        ),
        "raw_hash": raw_hash,
    }


def public_result(record: dict[str, Any], *, include_ids: bool = True) -> dict[str, Any]:
    text = (record.get("text") or "").strip()
    excerpt = text if len(text) <= 600 else text[:597].rstrip() + "..."
    result = {
        "person" if record.get("type") == "private" else "channel": record.get("display_name") or "Без имени",
        "username": record.get("username"),
        "timestamp": record.get("date"),
        "excerpt": excerpt,
        "media_type": record.get("media_type"),
        "media_name": record.get("media_name"),
        "media_metadata": json.loads(record.get("media_metadata_json") or "{}"),
        "content_trust": "external_untrusted",
    }
    if include_ids:
        result["peer_id"] = int(record["peer_id"])
        result["message_id"] = int(record["message_id"])
    return result
