from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from ..storage.repositories import ReaderRepository
from ..telegram.dialogs import peer_record, private_human_dialogs
from ..telegram.read_state import fetch_read_boundaries
from ..telegram.search import is_real_private_incoming, message_record, public_result


class UnreadService:
    def __init__(self, registry: Any, repository: ReaderRepository, settings: Any):
        self.registry = registry
        self.repository = repository
        self.settings = settings
        self._reconcile_lock = asyncio.Lock()

    async def reconcile(self) -> dict[str, int]:
        async with self._reconcile_lock:
            client = self.registry.primary()
            me = await client.get_me()
            dialogs = [dialog async for dialog in private_human_dialogs(client, int(me.id))]
            boundaries = await fetch_read_boundaries(client, [dialog.chat.id for dialog in dialogs])
            ingested = 0
            for dialog in dialogs:
                chat = dialog.chat
                peer_id = int(chat.id)
                peer = peer_record(chat, archived=bool(getattr(dialog, "folder_id", 0) == 1))
                await asyncio.to_thread(self.repository.upsert_peer, peer)
                state = boundaries.get(peer_id)
                if state is None:
                    continue
                unread_count = int(state["unread_count"])
                actual_unread_ids: list[int] = []
                if unread_count > 0:
                    limit = min(self.settings.max_unread_messages, max(unread_count + 20, 50))
                    async for message in client.get_chat_history(peer_id, limit=limit):
                        if int(message.id) <= int(state["read_inbox_max_id"]):
                            break
                        if not is_real_private_incoming(message, int(me.id)):
                            continue
                        await asyncio.to_thread(
                            self.repository.upsert_message,
                            message_record(message, state["read_inbox_max_id"]),
                        )
                        actual_unread_ids.append(int(message.id))
                        ingested += 1
                await asyncio.to_thread(
                    self.repository.update_dialog_state,
                    peer_id, state["read_inbox_max_id"], state["unread_count"],
                    state["last_message_id"],
                )
                if unread_count <= self.settings.max_unread_messages:
                    await asyncio.to_thread(
                        self.repository.reconcile_unread_set,
                        peer_id, state["read_inbox_max_id"], actual_unread_ids,
                    )
            return {"dialogs": len(dialogs), "messages": ingested}

    async def unread(
        self, owner_id: str, mode: str = "new_only", since: str | None = None,
        max_people: int = 20, max_messages_per_person: int = 20,
    ) -> dict[str, Any]:
        await self.reconcile()
        reservation = await asyncio.to_thread(
            self.repository.reserve_unread,
            owner_id, mode, since, max_people, max_messages_per_person,
            self.settings.reservation_ttl_seconds,
        )
        grouped: OrderedDict[int, dict[str, Any]] = OrderedDict()
        for row in reservation["messages"]:
            peer_id = int(row["peer_id"])
            group = grouped.setdefault(peer_id, {
                "person": row["display_name"],
                "username": row.get("username"),
                "messages": [],
            })
            group["messages"].append(public_result(row))
        return {
            "mode": mode,
            "batch_id": reservation["batch_id"],
            "reservation_expires_at": reservation["expires_at"],
            "people": list(grouped.values()),
            "people_count": len(grouped),
            "message_count": sum(len(item["messages"]) for item in grouped.values()),
            "telegram_state_refreshed": True,
            "surface_state_changed": False,
        }

    async def commit(self, owner_id: str, batch_id: str) -> dict[str, Any]:
        count = await asyncio.to_thread(self.repository.commit_surface_batch, batch_id, owner_id)
        return {"committed": count > 0, "message_count": count, "batch_id": batch_id}
