from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
from typing import Any

from ..storage.repositories import ReaderRepository


def _person_score(query: str, person: dict[str, Any]) -> float:
    needle = query.casefold().strip().lstrip("@")
    candidates = [person.get("display_name") or "", person.get("username") or ""]
    scores = []
    for value in candidates:
        folded = value.casefold().lstrip("@")
        scores.append(1.0 if folded == needle else SequenceMatcher(None, needle, folded).ratio())
    return max(scores, default=0.0)


class MarkReadService:
    def __init__(self, registry: Any, repository: ReaderRepository, settings: Any, unread_service: Any):
        self.registry = registry
        self.repository = repository
        self.settings = settings
        self.unread_service = unread_service

    async def resolve_person(self, person: str) -> dict[str, Any]:
        await self.unread_service.reconcile()
        candidates = await asyncio.to_thread(self.repository.find_people, person, 50)
        if not candidates:
            candidates = await asyncio.to_thread(self.repository.find_people, None, 100)
        ranked = sorted(candidates, key=lambda item: _person_score(person, item), reverse=True)
        if not ranked or _person_score(person, ranked[0]) < 0.45:
            raise LookupError("Человек не найден среди личных диалогов")
        if len(ranked) > 1:
            first, second = _person_score(person, ranked[0]), _person_score(person, ranked[1])
            if first < 0.9 and abs(first - second) < 0.04:
                raise LookupError("Имя неоднозначно; уточните имя или username")
        return ranked[0]

    async def prepare(
        self, owner_id: str, person: str, max_message_id: int | None = None,
    ) -> dict[str, Any]:
        peer = await self.resolve_person(person)
        rows = await asyncio.to_thread(
            self.repository.unread_for_peer, int(peer["peer_id"]), max_message_id,
        )
        if not rows:
            return {
                "confirmation_required": False,
                "person": peer["display_name"],
                "message_count": 0,
                "detail": "У этого человека нет подходящих непрочитанных сообщений.",
            }
        boundary = max(int(row["message_id"]) for row in rows)
        token = await asyncio.to_thread(
            self.repository.create_confirmation,
            owner_id, int(peer["peer_id"]), boundary, len(rows),
            self.settings.confirmation_ttl_seconds,
        )
        return {
            "confirmation_required": True,
            "confirmation_token": token,
            "expires_in_seconds": self.settings.confirmation_ttl_seconds,
            "person": peer["display_name"],
            "message_count": len(rows),
            "max_message_id": boundary,
            "warning": "Telegram отметит прочитанными все входящие сообщения этого диалога с ID не выше указанной границы.",
            "state_changed": False,
        }

    async def confirm(self, owner_id: str, token: str) -> dict[str, Any]:
        confirmation = await asyncio.to_thread(self.repository.consume_confirmation, token, owner_id)
        if not confirmation:
            raise PermissionError("Confirmation token недействителен, уже использован или истёк")
        client = self.registry.primary()
        peer_id = int(confirmation["peer_id"])
        max_message_id = int(confirmation["max_message_id"])
        acknowledged = await client.read_chat_history(peer_id, max_id=max_message_id)
        if not acknowledged:
            raise RuntimeError("Telegram не подтвердил изменение read state")
        changed = await asyncio.to_thread(self.repository.mark_read_locally, peer_id, max_message_id)
        return {
            "confirmed": True,
            "peer_id": peer_id,
            "max_message_id": max_message_id,
            "messages_marked_read": changed,
        }
