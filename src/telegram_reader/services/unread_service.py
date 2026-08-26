from __future__ import annotations

import asyncio
import logging
import math
from collections import OrderedDict
from typing import Any

from pyrogram.errors import FloodWait

from ..storage.repositories import ReaderRepository
from ..telegram.dialogs import peer_record, private_human_dialogs
from ..telegram.read_state import fetch_read_boundaries
from ..telegram.search import is_real_private_incoming, message_record, public_result


logger = logging.getLogger("telegram_reader.unread")


class UnreadService:
    def __init__(self, registry: Any, repository: ReaderRepository, settings: Any):
        self.registry = registry
        self.repository = repository
        self.settings = settings
        self._reconcile_lock = asyncio.Lock()
        self._next_reconcile_at = 0.0
        self._last_reconcile: dict[str, Any] = {
            "refreshed": False,
            "performed": False,
            "reason": "not_started",
            "dialogs": 0,
            "messages": 0,
        }

    @staticmethod
    def _flood_seconds(error: FloodWait) -> int:
        return max(1, int(getattr(error, "value", 30) or 30))

    def defer_for_flood_wait(self, seconds: int) -> None:
        loop = asyncio.get_running_loop()
        delay = max(
            int(seconds) + 5,
            int(getattr(self.settings, "reconcile_min_interval_seconds", 60)),
        )
        self._next_reconcile_at = max(self._next_reconcile_at, loop.time() + delay)
        self._last_reconcile = {
            **self._last_reconcile,
            "refreshed": False,
            "performed": True,
            "reason": "flood_wait",
            "retry_after_seconds": delay,
        }

    async def reconcile(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._reconcile_lock.locked():
            return {
                **self._last_reconcile,
                "refreshed": False,
                "performed": False,
                "reason": "in_progress",
                "retry_after_seconds": max(1, math.ceil(self._next_reconcile_at - now)),
            }

        async with self._reconcile_lock:
            now = loop.time()
            if now < self._next_reconcile_at:
                return {
                    **self._last_reconcile,
                    "performed": False,
                    "reason": "recent" if self._last_reconcile.get("refreshed") else self._last_reconcile.get("reason", "cooldown"),
                    "retry_after_seconds": max(1, math.ceil(self._next_reconcile_at - now)),
                }

            client = self.registry.primary()
            self_id = await self.registry.self_id(client)
            try:
                dialogs = [
                    dialog async for dialog in private_human_dialogs(
                        client, self_id, self.settings.max_dialogs_per_reconcile,
                    )
                ]
                tracked_ids = await asyncio.to_thread(self.repository.unread_peer_ids)
                relevant: list[Any] = []
                for dialog in dialogs:
                    chat = dialog.chat
                    peer_id = int(chat.id)
                    await asyncio.to_thread(
                        self.repository.upsert_peer,
                        peer_record(chat, archived=bool(getattr(dialog, "folder_id", 0) == 1)),
                    )
                    dialog_unread = int(getattr(dialog, "unread_messages_count", 0) or 0)
                    if dialog_unread > 0 or peer_id in tracked_ids:
                        relevant.append(dialog)

                boundaries = await fetch_read_boundaries(
                    client, [dialog.chat.id for dialog in relevant],
                )
                ingested = 0
                for dialog in relevant:
                    chat = dialog.chat
                    peer_id = int(chat.id)
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
                            if not is_real_private_incoming(message, self_id):
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
            except FloodWait as error:
                seconds = self._flood_seconds(error)
                self.defer_for_flood_wait(seconds)
                logger.warning(
                    "Telegram Reader reconciliation paused after FloodWait; retry in %ss",
                    self._last_reconcile["retry_after_seconds"],
                )
                return dict(self._last_reconcile)

            interval = int(getattr(self.settings, "reconcile_min_interval_seconds", 60))
            self._next_reconcile_at = loop.time() + max(0, interval)
            self._last_reconcile = {
                "refreshed": True,
                "performed": True,
                "reason": "completed",
                "dialogs": len(dialogs),
                "relevant_dialogs": len(relevant),
                "messages": ingested,
                "retry_after_seconds": max(0, interval),
            }
            return dict(self._last_reconcile)

    async def unread(
        self, owner_id: str, mode: str = "new_only", since: str | None = None,
        max_people: int = 20, max_messages_per_person: int = 20,
    ) -> dict[str, Any]:
        sync = await self.reconcile()
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
            "telegram_state_refreshed": bool(sync.get("refreshed")),
            "telegram_sync": sync,
            "surface_state_changed": False,
        }

    async def commit(self, owner_id: str, batch_id: str) -> dict[str, Any]:
        count = await asyncio.to_thread(self.repository.commit_surface_batch, batch_id, owner_id)
        return {"committed": count > 0, "message_count": count, "batch_id": batch_id}
