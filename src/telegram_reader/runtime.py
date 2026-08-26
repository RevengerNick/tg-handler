from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Iterable

from .config import get_reader_settings
from .services import MarkReadService, SearchService, UnreadService
from .storage import Database
from .storage.database import utc_iso
from .storage.repositories import ReaderRepository
from .telegram.client import ClientRegistry
from .telegram.dialogs import is_private_human_chat, peer_record
from .telegram.events import install_handlers
from .telegram.read_state import fetch_read_boundaries
from .telegram.search import message_record


logger = logging.getLogger("telegram_reader.runtime")


class ReaderRuntime:
    def __init__(self) -> None:
        self.settings = get_reader_settings()
        self.database = Database(self.settings.database_path)
        self.database.migrate()
        self.repository = ReaderRepository(self.database)
        self.registry = ClientRegistry()
        self.unread = UnreadService(self.registry, self.repository, self.settings)
        self.search = SearchService(self.registry, self.repository, self.settings, self.unread)
        self.mark_read = MarkReadService(self.registry, self.repository, self.settings, self.unread)

    async def register_client(self, client: Any) -> None:
        await self.registry.add(client)
        await install_handlers(client, self)
        try:
            await self.unread.reconcile()
        except Exception as error:
            logger.warning("Initial Telegram Reader reconciliation failed: %s", type(error).__name__)

    async def unregister_client(self, client: Any) -> None:
        await self.registry.remove(client)

    async def ingest_message(self, message: Any) -> None:
        client = self.registry.primary()
        me = await client.get_me()
        chat = getattr(message, "chat", None)
        if not is_private_human_chat(chat, int(me.id)) or getattr(message, "service", None) is not None:
            return
        peer_id = int(chat.id)
        await asyncio.to_thread(self.repository.upsert_peer, peer_record(chat))
        state = await asyncio.to_thread(self.repository.get_dialog_state, peer_id)
        if state is None:
            boundaries = await fetch_read_boundaries(client, [peer_id])
            state = boundaries.get(peer_id, {"read_inbox_max_id": 0, "unread_count": 0, "last_message_id": int(message.id)})
        await asyncio.to_thread(
            self.repository.upsert_message,
            message_record(message, int(state.get("read_inbox_max_id", 0))),
        )
        last_id = max(int(state.get("last_message_id", 0)), int(message.id))
        unread_count = await asyncio.to_thread(self.repository.count_unread, peer_id)
        await asyncio.to_thread(
            self.repository.update_dialog_state,
            peer_id, int(state.get("read_inbox_max_id", 0)), unread_count, last_id,
        )

    async def mark_deleted(self, peer_id: int, message_ids: Iterable[int]) -> None:
        await asyncio.to_thread(self.repository.mark_deleted, int(peer_id), list(message_ids))

    async def apply_read_update(self, peer_id: int, max_id: int, unread_count: int) -> None:
        state = await asyncio.to_thread(self.repository.get_dialog_state, int(peer_id))
        if state is None:
            return
        await asyncio.to_thread(
            self.repository.update_dialog_state,
            int(peer_id), int(max_id), int(unread_count), int(state.get("last_message_id", max_id)), utc_iso(),
        )

    def status(self) -> dict[str, Any]:
        with self.database.connection() as connection:
            counts = {
                "peers": connection.execute("SELECT COUNT(*) n FROM peers").fetchone()["n"],
                "messages": connection.execute("SELECT COUNT(*) n FROM messages WHERE deleted_at IS NULL").fetchone()["n"],
                "telegram_unread": connection.execute("SELECT COUNT(*) n FROM messages WHERE telegram_unread=1 AND deleted_at IS NULL").fetchone()["n"],
            }
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        return {
            "version": "1.0.0",
            "enabled": self.settings.enabled,
            "read_only": True,
            "mark_read_requires_confirmation": True,
            "ready": self.registry.ready and self.settings.auth_configured,
            "telegram_connected": self.registry.ready,
            "client_count": self.registry.count,
            "auth_configured": self.settings.auth_configured,
            "database_journal_mode": journal_mode,
            "counts": counts,
            "timezone": self.settings.timezone,
        }


_runtime: ReaderRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> ReaderRuntime:
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = ReaderRuntime()
    return _runtime
