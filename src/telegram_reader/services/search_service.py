from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from ..storage.repositories import ReaderRepository
from ..telegram.dialogs import is_channel_chat, is_private_human_chat, joined_channel_dialogs, peer_record
from ..telegram.search import message_record, public_result


def _fold(value: str) -> str:
    return " ".join((value or "").casefold().split())


def lexical_score(query: str, text: str, mode: str) -> float:
    query_folded, text_folded = _fold(query), _fold(text)
    terms = [part for part in query_folded.split() if part]
    if not query_folded or not terms:
        return 0.0
    if mode == "exact":
        return 1.0 if query_folded in text_folded else 0.0
    hits = sum(1 for term in terms if term in text_folded)
    if mode == "all_terms":
        return (0.75 + 0.25 * SequenceMatcher(None, query_folded, text_folded).ratio()) if hits == len(terms) else 0.0
    if mode == "any_terms" or mode == "semantic":
        return (hits / len(terms)) if hits else 0.0
    token_score = hits / len(terms)
    ratio = SequenceMatcher(None, query_folded, text_folded[: max(len(query_folded) * 4, 200)]).ratio()
    return max(token_score, ratio)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cursor(offset: int, signature: str) -> str:
    payload = json.dumps({"offset": offset, "signature": signature}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _read_cursor(value: str | None, signature: str) -> int:
    if not value:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("signature") != signature:
            raise ValueError
        return max(0, int(payload.get("offset", 0)))
    except Exception as error:
        raise ValueError("Некорректный или устаревший cursor") from error


def _cache_key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class SearchService:
    def __init__(self, registry: Any, repository: ReaderRepository, settings: Any, unread_service: Any):
        self.registry = registry
        self.repository = repository
        self.settings = settings
        self.unread_service = unread_service

    def _filter_and_page(
        self, rows: list[dict[str, Any]], query: str, mode: str,
        date_from: str | None, date_to: str | None, media_type: str | None,
        limit: int, cursor: str | None, signature_payload: dict[str, Any],
    ) -> dict[str, Any]:
        start, end = _parse_iso(date_from), _parse_iso(date_to)
        unique: dict[tuple[int, int], dict[str, Any]] = {}
        for row in rows:
            date = _parse_iso(row.get("date"))
            if start and (not date or date < start):
                continue
            if end and (not date or date > end):
                continue
            if media_type and row.get("media_type") != media_type:
                continue
            score = lexical_score(query, row.get("text") or "", mode)
            if score <= 0 or (mode == "fuzzy" and score < 0.3):
                continue
            row = dict(row)
            row["lexical_score"] = round(score, 6)
            unique[(int(row["peer_id"]), int(row["message_id"]))] = row
        ranked = sorted(unique.values(), key=lambda item: (item["lexical_score"], item.get("date") or ""), reverse=True)
        signature = hashlib.sha256(json.dumps(signature_payload, sort_keys=True).encode()).hexdigest()[:16]
        offset = _read_cursor(cursor, signature)
        bounded = max(1, min(100, limit))
        page = ranked[offset:offset + bounded]
        next_value = _cursor(offset + bounded, signature) if offset + bounded < len(ranked) else None
        results = []
        for row in page:
            result = public_result(row)
            result["lexical_score"] = row["lexical_score"]
            if row.get("permalink"):
                result["permalink"] = row["permalink"]
            results.append(result)
        return {"results": results, "next_cursor": next_value, "total_candidates": len(ranked)}

    async def _ingest_server_message(self, message: Any, read_boundary: int = 0) -> dict[str, Any] | None:
        chat = getattr(message, "chat", None)
        if chat is None or getattr(message, "service", None) is not None:
            return None
        peer = peer_record(chat)
        await asyncio.to_thread(self.repository.upsert_peer, peer)
        record = message_record(message, read_boundary)
        if peer["type"] == "channel":
            record["telegram_unread"] = False
        await asyncio.to_thread(self.repository.upsert_message, record)
        return {**record, **peer, "permalink": getattr(message, "link", None)}

    async def search_private(
        self, query: str, person: str | None, mode: str,
        date_from: str | None, date_to: str | None, media_type: str | None,
        limit: int, cursor: str | None,
    ) -> dict[str, Any]:
        await self.unread_service.reconcile()
        cache_payload = {
            "query": query, "person": person, "mode": mode, "date_from": date_from,
            "date_to": date_to, "media_type": media_type, "limit": limit, "cursor": cursor,
        }
        cache_key = _cache_key(cache_payload)
        cached = await asyncio.to_thread(self.repository.get_search_cache, "private", cache_key)
        if cached is not None:
            return {**cached, "cache_hit": True}
        client = self.registry.primary()
        self_id = await self.registry.self_id(client)
        local = await asyncio.to_thread(
            self.repository.search_local, "private", query, self.settings.max_search_candidates,
        )
        if mode == "fuzzy":
            recent = await asyncio.to_thread(
                self.repository.recent_local, "private", self.settings.max_search_candidates,
            )
            local.extend(recent)
        selected_peer_ids: set[int] | None = None
        if person:
            people = await asyncio.to_thread(self.repository.find_people, person, 50)
            ranked_people = sorted(
                people,
                key=lambda item: max(
                    SequenceMatcher(None, _fold(person), _fold(item.get("display_name") or "")).ratio(),
                    SequenceMatcher(None, _fold(person).lstrip("@"), _fold(item.get("username") or "").lstrip("@")).ratio(),
                ),
                reverse=True,
            )
            if not ranked_people:
                return {"results": [], "next_cursor": None, "total_candidates": 0, "semantic_available": False}
            selected_peer_ids = {int(ranked_people[0]["peer_id"])}
            local = [row for row in local if int(row["peer_id"]) in selected_peer_ids]

        server_rows: list[dict[str, Any]] = []
        if selected_peer_ids:
            for peer_id in selected_peer_ids:
                source = (
                    client.get_chat_history(peer_id, limit=self.settings.max_search_candidates)
                    if mode == "fuzzy"
                    else client.search_messages(peer_id, query=query, limit=self.settings.max_search_candidates)
                )
                async for message in source:
                    item = await self._ingest_server_message(message)
                    if item and is_private_human_chat(message.chat, self_id):
                        server_rows.append(item)
        else:
            async for message in client.search_global(query=query, limit=self.settings.max_search_candidates):
                if not is_private_human_chat(getattr(message, "chat", None), self_id):
                    continue
                item = await self._ingest_server_message(message)
                if item:
                    server_rows.append(item)

        payload = {"scope": "private", "query": query, "person": person, "mode": mode, "date_from": date_from, "date_to": date_to, "media_type": media_type}
        page = self._filter_and_page(local + server_rows, query, mode, date_from, date_to, media_type, limit, cursor, payload)
        result = {**page, "semantic_available": False, "source": "telegram_server_and_local", "cache_hit": False}
        await asyncio.to_thread(self.repository.put_search_cache, "private", cache_key, result)
        return result

    async def search_channels(
        self, query: str, mode: str, scope: str, channel_names: list[str],
        date_from: str | None, date_to: str | None, limit: int, cursor: str | None,
        include_context: bool, semantic_top_k: int, confirm_public_global: bool,
    ) -> dict[str, Any]:
        if scope == "public_global" and not confirm_public_global:
            raise PermissionError("public_global требует явного confirm_public_global=true")
        if scope == "public_global":
            raise NotImplementedError(
                "Глобальный поиск по всем публичным каналам недоступен в установленном Pyrogram 2.0.106; "
                "поиск не выполнен и платные Telegram-операции не использовались."
            )
        cache_payload = {
            "query": query, "mode": mode, "scope": scope, "channel_names": channel_names,
            "date_from": date_from, "date_to": date_to, "limit": limit, "cursor": cursor,
            "include_context": include_context, "semantic_top_k": semantic_top_k,
        }
        cache_key = _cache_key(cache_payload)
        cached = await asyncio.to_thread(self.repository.get_search_cache, "channels", cache_key)
        if cached is not None:
            return {**cached, "cache_hit": True}
        client = self.registry.primary()
        joined = [dialog async for dialog in joined_channel_dialogs(client)]
        joined_ids = {int(dialog.chat.id) for dialog in joined}
        wanted = {_fold(item).lstrip("@") for item in channel_names if item.strip()}
        if wanted:
            joined_ids = {
                int(dialog.chat.id) for dialog in joined
                if _fold(getattr(dialog.chat, "title", "")) in wanted
                or _fold(getattr(dialog.chat, "username", "")).lstrip("@") in wanted
            }
        rows: list[dict[str, Any]] = []
        async for message in client.search_global(query=query, limit=self.settings.max_search_candidates):
            chat = getattr(message, "chat", None)
            if not is_channel_chat(chat):
                continue
            if scope == "joined_channels" and int(chat.id) not in joined_ids:
                continue
            if wanted and int(chat.id) not in joined_ids:
                continue
            item = await self._ingest_server_message(message)
            if item:
                rows.append(item)
        local = await asyncio.to_thread(
            self.repository.search_local, "channel", query, self.settings.max_search_candidates,
        )
        if scope == "joined_channels":
            local = [row for row in local if int(row["peer_id"]) in joined_ids]
        payload = {"scope": scope, "query": query, "channels": sorted(wanted), "mode": mode, "date_from": date_from, "date_to": date_to}
        lexical_mode = "any_terms" if mode == "semantic" else mode
        page = self._filter_and_page(local + rows, query, lexical_mode, date_from, date_to, None, max(limit, semantic_top_k), cursor, payload)
        if include_context:
            for result in page["results"]:
                result["context_available"] = True
        result = {
            **page,
            "semantic_requested": mode == "semantic",
            "semantic_available": False,
            "semantic_stage": "candidate_pool",
            "source": "telegram_server_and_local",
            "cache_hit": False,
        }
        await asyncio.to_thread(self.repository.put_search_cache, "channels", cache_key, result)
        return result

    async def context(self, peer_id: int, message_id: int, before: int, after: int) -> dict[str, Any]:
        known_peer = await asyncio.to_thread(self.repository.get_peer, int(peer_id))
        if not known_peer or known_peer.get("type") not in {"private", "channel"} or bool(known_peer.get("is_bot")):
            raise PermissionError("Контекст доступен только для результата личного или канального поиска")
        client = self.registry.primary()
        before, after = max(0, min(10, before)), max(0, min(10, after))
        ids = list(range(max(1, message_id - before), message_id + after + 1))
        messages = await client.get_messages(peer_id, message_ids=ids)
        if not isinstance(messages, list):
            messages = [messages]
        rows = []
        for message in messages:
            if not message or bool(getattr(message, "empty", False)):
                continue
            item = await self._ingest_server_message(message)
            if item:
                rows.append(item)
        rows.sort(key=lambda item: int(item["message_id"]))
        return {
            "peer_id": peer_id,
            "message_id": message_id,
            "messages": [public_result(row) | ({"permalink": row["permalink"]} if row.get("permalink") else {}) for row in rows],
            "content_trust": "external_untrusted",
        }
