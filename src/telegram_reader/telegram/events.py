from __future__ import annotations

from typing import Any

from pyrogram.handlers import DeletedMessagesHandler, EditedMessageHandler, MessageHandler, RawUpdateHandler

from .read_state import read_update


async def install_handlers(client: Any, runtime: Any) -> None:
    if getattr(client, "_vex_reader_handlers_installed", False):
        return

    async def on_message(_client: Any, message: Any) -> None:
        await runtime.ingest_message(message)

    async def on_edited(_client: Any, message: Any) -> None:
        await runtime.ingest_message(message)

    async def on_deleted(_client: Any, messages: list[Any]) -> None:
        by_peer: dict[int, list[int]] = {}
        unknown_peer = False
        for message in messages or []:
            chat = getattr(message, "chat", None)
            if chat is not None:
                by_peer.setdefault(int(chat.id), []).append(int(message.id))
            else:
                unknown_peer = True
        for peer_id, message_ids in by_peer.items():
            await runtime.mark_deleted(peer_id, message_ids)
        if unknown_peer:
            await runtime.unread.reconcile()

    async def on_raw(_client: Any, update: Any, _users: Any, _chats: Any) -> None:
        parsed = read_update(update)
        if parsed:
            peer_id, max_id, unread_count = parsed
            await runtime.apply_read_update(peer_id, max_id, unread_count)

    client.add_handler(MessageHandler(on_message), group=100)
    client.add_handler(EditedMessageHandler(on_edited), group=100)
    client.add_handler(DeletedMessagesHandler(on_deleted), group=100)
    client.add_handler(RawUpdateHandler(on_raw), group=100)
    client._vex_reader_handlers_installed = True
