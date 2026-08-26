from __future__ import annotations

from typing import Any, AsyncIterator

try:
    from pyrogram.enums import ChatType
except ImportError:  # pragma: no cover - only used by lightweight unit doubles
    ChatType = None


def type_name(chat: Any) -> str:
    value = getattr(chat, "type", "")
    value = getattr(value, "value", value)
    return str(value).lower()


def display_name(chat: Any) -> str:
    full_name = " ".join(
        part.strip() for part in (getattr(chat, "first_name", None), getattr(chat, "last_name", None))
        if isinstance(part, str) and part.strip()
    )
    return full_name or getattr(chat, "title", None) or getattr(chat, "username", None) or "Без имени"


def peer_record(chat: Any, archived: bool = False) -> dict[str, Any]:
    return {
        "peer_id": int(chat.id),
        "type": type_name(chat),
        "username": getattr(chat, "username", None),
        "display_name": display_name(chat),
        "is_bot": bool(getattr(chat, "is_bot", False)),
        "is_contact": bool(getattr(chat, "is_contact", False)),
        "is_archived": bool(archived),
    }


def is_private_human_chat(chat: Any, self_id: int | None = None) -> bool:
    return (
        type_name(chat) == "private"
        and not bool(getattr(chat, "is_bot", False))
        and (self_id is None or int(chat.id) != int(self_id))
    )


def is_channel_chat(chat: Any) -> bool:
    return type_name(chat) == "channel"


async def private_human_dialogs(client: Any, self_id: int) -> AsyncIterator[Any]:
    async for dialog in client.get_dialogs():
        if is_private_human_chat(dialog.chat, self_id):
            yield dialog


async def joined_channel_dialogs(client: Any) -> AsyncIterator[Any]:
    async for dialog in client.get_dialogs():
        if is_channel_chat(dialog.chat):
            yield dialog
