from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from ..database import Database, utc_iso, utc_now


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class ReaderRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert_peer(self, peer: dict[str, Any]) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO peers
                (peer_id, type, username, display_name, is_bot, is_contact, is_archived, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_id) DO UPDATE SET
                    type=excluded.type, username=excluded.username,
                    display_name=excluded.display_name, is_bot=excluded.is_bot,
                    is_contact=excluded.is_contact, is_archived=excluded.is_archived,
                    updated_at=excluded.updated_at""",
                (
                    int(peer["peer_id"]), peer["type"], peer.get("username"),
                    peer.get("display_name") or "Без имени", int(bool(peer.get("is_bot"))),
                    int(bool(peer.get("is_contact"))), int(bool(peer.get("is_archived"))),
                    peer.get("updated_at") or utc_iso(),
                ),
            )

    def upsert_message(self, message: dict[str, Any]) -> None:
        peer_id, message_id = int(message["peer_id"]), int(message["message_id"])
        with self.database.transaction(immediate=True) as connection:
            previous = connection.execute(
                "SELECT raw_hash FROM messages WHERE peer_id=? AND message_id=?",
                (peer_id, message_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO messages
                (peer_id, message_id, date, edit_date, direction, text, media_type,
                 media_name, media_metadata_json, telegram_unread, surfaced_at, deleted_at, raw_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peer_id, message_id) DO UPDATE SET
                    date=excluded.date, edit_date=excluded.edit_date,
                    direction=excluded.direction, text=excluded.text,
                    media_type=excluded.media_type, media_name=excluded.media_name,
                    media_metadata_json=excluded.media_metadata_json,
                    telegram_unread=excluded.telegram_unread,
                    deleted_at=excluded.deleted_at, raw_hash=excluded.raw_hash""",
                (
                    peer_id, message_id, message["date"], message.get("edit_date"),
                    message["direction"], message.get("text") or "",
                    message.get("media_type"), message.get("media_name"),
                    json.dumps(message.get("media_metadata") or {}, ensure_ascii=False),
                    int(bool(message.get("telegram_unread"))), message.get("surfaced_at"),
                    message.get("deleted_at"), message["raw_hash"],
                ),
            )
            peer = connection.execute(
                "SELECT display_name, username FROM peers WHERE peer_id=?", (peer_id,)
            ).fetchone()
            connection.execute(
                "DELETE FROM message_fts WHERE peer_id=? AND message_id=?", (peer_id, message_id)
            )
            if not message.get("deleted_at"):
                connection.execute(
                    "INSERT INTO message_fts(peer_id, message_id, text, display_name, username) VALUES(?, ?, ?, ?, ?)",
                    (
                        peer_id, message_id, message.get("text") or "",
                        peer["display_name"] if peer else "", peer["username"] if peer else "",
                    ),
                )
            if previous and previous["raw_hash"] != message["raw_hash"]:
                connection.execute(
                    "DELETE FROM embedding_cache WHERE peer_id=? AND message_id=?", (peer_id, message_id)
                )
                connection.execute(
                    "UPDATE messages SET surfaced_at=NULL WHERE peer_id=? AND message_id=?",
                    (peer_id, message_id),
                )
            if not previous or previous["raw_hash"] != message["raw_hash"]:
                connection.execute("DELETE FROM search_cache")

    def mark_deleted(self, peer_id: int, message_ids: Iterable[int], at: str | None = None) -> None:
        ids = sorted({int(item) for item in message_ids})
        if not ids:
            return
        deleted_at = at or utc_iso()
        with self.database.transaction(immediate=True) as connection:
            for message_id in ids:
                connection.execute(
                    "UPDATE messages SET deleted_at=?, telegram_unread=0 WHERE peer_id=? AND message_id=?",
                    (deleted_at, peer_id, message_id),
                )
                connection.execute(
                    "DELETE FROM message_fts WHERE peer_id=? AND message_id=?", (peer_id, message_id)
                )
                connection.execute(
                    "DELETE FROM embedding_cache WHERE peer_id=? AND message_id=?", (peer_id, message_id)
                )
            connection.execute("DELETE FROM search_cache")

    def update_dialog_state(
        self, peer_id: int, read_inbox_max_id: int, unread_count: int,
        last_message_id: int, refreshed_at: str | None = None,
    ) -> None:
        refreshed = refreshed_at or utc_iso()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO dialog_state
                (peer_id, read_inbox_max_id, unread_count, last_message_id, refreshed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(peer_id) DO UPDATE SET
                    read_inbox_max_id=excluded.read_inbox_max_id,
                    unread_count=excluded.unread_count,
                    last_message_id=excluded.last_message_id,
                    refreshed_at=excluded.refreshed_at""",
                (peer_id, max(0, read_inbox_max_id), max(0, unread_count), max(0, last_message_id), refreshed),
            )
            connection.execute(
                """UPDATE messages SET telegram_unread = CASE
                    WHEN direction='incoming' AND deleted_at IS NULL AND message_id > ? THEN 1
                    ELSE 0 END WHERE peer_id=?""",
                (max(0, read_inbox_max_id), peer_id),
            )

    def reconcile_unread_set(self, peer_id: int, read_inbox_max_id: int, actual_ids: Iterable[int]) -> int:
        ids = sorted({int(item) for item in actual_ids})
        actual = set(ids)
        now = utc_iso()
        with self.database.transaction(immediate=True) as connection:
            sql = """SELECT message_id FROM messages
                WHERE peer_id=? AND direction='incoming' AND message_id>? AND deleted_at IS NULL"""
            stored = [int(row["message_id"]) for row in connection.execute(sql, (peer_id, read_inbox_max_id)).fetchall()]
            missing = [message_id for message_id in stored if message_id not in actual]
            for message_id in missing:
                connection.execute(
                    "UPDATE messages SET deleted_at=?, telegram_unread=0 WHERE peer_id=? AND message_id=?",
                    (now, peer_id, message_id),
                )
                connection.execute(
                    "DELETE FROM message_fts WHERE peer_id=? AND message_id=?", (peer_id, message_id)
                )
                connection.execute(
                    "DELETE FROM embedding_cache WHERE peer_id=? AND message_id=?", (peer_id, message_id)
                )
            if missing:
                connection.execute("DELETE FROM search_cache")
            return len(missing)

    def get_dialog_state(self, peer_id: int) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM dialog_state WHERE peer_id=?", (peer_id,)).fetchone()
            return _row(row) or None

    def find_people(self, query: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(100, limit))
        with self.database.connection() as connection:
            if query:
                needle = f"%{query.strip()}%"
                rows = connection.execute(
                    """SELECT * FROM peers WHERE type='private' AND is_bot=0
                    AND (display_name LIKE ? COLLATE NOCASE OR username LIKE ? COLLATE NOCASE)
                    ORDER BY is_contact DESC, display_name COLLATE NOCASE LIMIT ?""",
                    (needle, needle, bounded),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM peers WHERE type='private' AND is_bot=0 ORDER BY is_contact DESC, display_name COLLATE NOCASE LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [_row(item) for item in rows]

    def get_peer(self, peer_id: int) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM peers WHERE peer_id=?", (peer_id,)).fetchone()
            return _row(row) or None

    def reserve_unread(
        self, owner_id: str, mode: str, since: str | None,
        max_people: int, max_messages_per_person: int, ttl_seconds: int,
    ) -> dict[str, Any]:
        now = utc_now()
        now_iso = utc_iso(now)
        expires = utc_iso(now + timedelta(seconds=ttl_seconds))
        batch_id = secrets.token_urlsafe(18)
        max_people = max(1, min(100, max_people))
        max_messages_per_person = max(1, min(100, max_messages_per_person))
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE surface_batches SET status='expired' WHERE status='reserved' AND expires_at <= ?",
                (now_iso,),
            )
            sql = """SELECT m.*, p.display_name, p.username, p.type, p.is_bot
                FROM messages m JOIN peers p ON p.peer_id=m.peer_id
                WHERE m.telegram_unread=1 AND m.direction='incoming' AND m.deleted_at IS NULL
                  AND p.type='private' AND p.is_bot=0"""
            params: list[Any] = []
            if mode == "new_only":
                sql += " AND m.surfaced_at IS NULL AND NOT EXISTS (SELECT 1 FROM surface_batch_messages sbm JOIN surface_batches sb ON sb.batch_id=sbm.batch_id WHERE sbm.peer_id=m.peer_id AND sbm.message_id=m.message_id AND sb.status='reserved' AND sb.expires_at > ?)"
                params.append(now_iso)
            if since:
                sql += " AND m.date >= ?"
                params.append(since)
            sql += " ORDER BY m.date ASC, m.peer_id, m.message_id"
            rows = [_row(item) for item in connection.execute(sql, params).fetchall()]
            grouped: dict[int, list[dict[str, Any]]] = {}
            for item in rows:
                peer_id = int(item["peer_id"])
                if peer_id not in grouped and len(grouped) >= max_people:
                    continue
                bucket = grouped.setdefault(peer_id, [])
                if len(bucket) < max_messages_per_person:
                    bucket.append(item)
            selected = [item for bucket in grouped.values() for item in bucket]
            if selected:
                connection.execute(
                    "INSERT INTO surface_batches(batch_id, owner_id, created_at, expires_at, status) VALUES(?, ?, ?, ?, 'reserved')",
                    (batch_id, owner_id, now_iso, expires),
                )
                connection.executemany(
                    "INSERT INTO surface_batch_messages(batch_id, peer_id, message_id) VALUES(?, ?, ?)",
                    [(batch_id, item["peer_id"], item["message_id"]) for item in selected],
                )
            else:
                batch_id = ""
        return {"batch_id": batch_id or None, "expires_at": expires if selected else None, "messages": selected}

    def commit_surface_batch(self, batch_id: str, owner_id: str) -> int:
        now = utc_iso()
        with self.database.transaction(immediate=True) as connection:
            batch = connection.execute(
                "SELECT * FROM surface_batches WHERE batch_id=? AND owner_id=?", (batch_id, owner_id)
            ).fetchone()
            if not batch or batch["status"] != "reserved" or batch["expires_at"] <= now:
                if batch and batch["status"] == "reserved":
                    connection.execute("UPDATE surface_batches SET status='expired' WHERE batch_id=?", (batch_id,))
                return 0
            rows = connection.execute(
                "SELECT peer_id, message_id FROM surface_batch_messages WHERE batch_id=?", (batch_id,)
            ).fetchall()
            connection.executemany(
                "UPDATE messages SET surfaced_at=COALESCE(surfaced_at, ?) WHERE peer_id=? AND message_id=?",
                [(now, row["peer_id"], row["message_id"]) for row in rows],
            )
            connection.execute(
                "UPDATE surface_batches SET status='delivered', delivered_at=? WHERE batch_id=?", (now, batch_id)
            )
            return len(rows)

    def search_local(self, scope: str, query: str, limit: int = 150) -> list[dict[str, Any]]:
        terms = [part for part in query.replace('"', " ").split() if part]
        bounded = max(1, min(300, limit))
        peer_types = ("private",) if scope == "private" else ("channel",)
        with self.database.connection() as connection:
            rows = []
            if terms:
                fts_query = " OR ".join(f'"{term}"' for term in terms)
                try:
                    rows = connection.execute(
                        """SELECT m.*, p.display_name, p.username, p.type
                        FROM message_fts f
                        JOIN messages m ON m.peer_id=CAST(f.peer_id AS INTEGER) AND m.message_id=CAST(f.message_id AS INTEGER)
                        JOIN peers p ON p.peer_id=m.peer_id
                        WHERE message_fts MATCH ? AND p.type=? AND p.is_bot=0 AND m.deleted_at IS NULL
                        ORDER BY bm25(message_fts), m.date DESC LIMIT ?""",
                        (fts_query, peer_types[0], bounded),
                    ).fetchall()
                except Exception:
                    rows = []
            if not rows:
                where = "p.type=? AND p.is_bot=0 AND m.deleted_at IS NULL"
                params: list[Any] = [peer_types[0]]
                if terms:
                    where += " AND (" + " OR ".join("m.text LIKE ? COLLATE NOCASE" for _ in terms) + ")"
                    params.extend(f"%{term}%" for term in terms)
                params.append(bounded)
                rows = connection.execute(
                    f"""SELECT m.*, p.display_name, p.username, p.type
                    FROM messages m JOIN peers p ON p.peer_id=m.peer_id
                    WHERE {where} ORDER BY m.date DESC, m.message_id DESC LIMIT ?""",
                    params,
                ).fetchall()
        return [_row(item) for item in rows]

    def recent_local(self, scope: str, limit: int = 300) -> list[dict[str, Any]]:
        peer_type = "private" if scope == "private" else "channel"
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT m.*, p.display_name, p.username, p.type FROM messages m
                JOIN peers p ON p.peer_id=m.peer_id
                WHERE p.type=? AND p.is_bot=0 AND m.deleted_at IS NULL
                ORDER BY m.date DESC, m.message_id DESC LIMIT ?""",
                (peer_type, max(1, min(500, limit))),
            ).fetchall()
        return [_row(item) for item in rows]

    def get_messages(self, peer_id: int, message_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = sorted({int(item) for item in message_ids if int(item) > 0})
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""SELECT m.*, p.display_name, p.username, p.type FROM messages m
                JOIN peers p ON p.peer_id=m.peer_id
                WHERE m.peer_id=? AND m.message_id IN ({placeholders}) AND m.deleted_at IS NULL
                ORDER BY m.message_id""",
                [peer_id, *ids],
            ).fetchall()
        return [_row(item) for item in rows]

    def create_confirmation(
        self, owner_id: str, peer_id: int, max_message_id: int,
        message_count: int, ttl_seconds: int,
    ) -> str:
        token = secrets.token_urlsafe(24)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = utc_now()
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO mark_read_confirmations
                (token_hash, owner_id, peer_id, max_message_id, message_count, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    token_hash, owner_id, peer_id, max_message_id, message_count,
                    utc_iso(now), utc_iso(now + timedelta(seconds=ttl_seconds)),
                ),
            )
        return token

    def consume_confirmation(self, token: str, owner_id: str) -> dict[str, Any] | None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = utc_iso()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM mark_read_confirmations WHERE token_hash=? AND owner_id=?",
                (token_hash, owner_id),
            ).fetchone()
            if not row or row["confirmed_at"] or row["expires_at"] <= now:
                return None
            connection.execute(
                "UPDATE mark_read_confirmations SET confirmed_at=? WHERE token_hash=?", (now, token_hash)
            )
            return _row(row)

    def unread_for_peer(self, peer_id: int, max_message_id: int | None = None) -> list[dict[str, Any]]:
        sql = """SELECT m.*, p.display_name, p.username FROM messages m JOIN peers p ON p.peer_id=m.peer_id
            WHERE m.peer_id=? AND m.telegram_unread=1 AND m.direction='incoming' AND m.deleted_at IS NULL"""
        params: list[Any] = [peer_id]
        if max_message_id is not None:
            sql += " AND m.message_id <= ?"
            params.append(max_message_id)
        sql += " ORDER BY m.message_id"
        with self.database.connection() as connection:
            return [_row(item) for item in connection.execute(sql, params).fetchall()]

    def count_unread(self, peer_id: int) -> int:
        with self.database.connection() as connection:
            return int(connection.execute(
                """SELECT COUNT(*) n FROM messages WHERE peer_id=? AND telegram_unread=1
                AND direction='incoming' AND deleted_at IS NULL""",
                (peer_id,),
            ).fetchone()["n"])

    def mark_read_locally(self, peer_id: int, max_message_id: int) -> int:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                """UPDATE messages SET telegram_unread=0
                WHERE peer_id=? AND message_id<=? AND telegram_unread=1""",
                (peer_id, max_message_id),
            ).rowcount
            state = connection.execute("SELECT * FROM dialog_state WHERE peer_id=?", (peer_id,)).fetchone()
            if state:
                remaining = connection.execute(
                    "SELECT COUNT(*) n FROM messages WHERE peer_id=? AND telegram_unread=1 AND deleted_at IS NULL",
                    (peer_id,),
                ).fetchone()["n"]
                connection.execute(
                    "UPDATE dialog_state SET read_inbox_max_id=MAX(read_inbox_max_id, ?), unread_count=?, refreshed_at=? WHERE peer_id=?",
                    (max_message_id, remaining, utc_iso(), peer_id),
                )
            return changed

    def cache_embedding(self, peer_id: int, message_id: int, content_hash: str, model: str, vector: list[float]) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO embedding_cache
                (peer_id, message_id, content_hash, model, vector_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (peer_id, message_id, content_hash, model, json.dumps(vector), utc_iso()),
            )

    def get_embedding(self, peer_id: int, message_id: int, content_hash: str, model: str) -> list[float] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT vector_json FROM embedding_cache
                WHERE peer_id=? AND message_id=? AND content_hash=? AND model=?""",
                (peer_id, message_id, content_hash, model),
            ).fetchone()
        return json.loads(row["vector_json"]) if row else None

    def get_search_cache(self, scope: str, query_hash: str) -> dict[str, Any] | None:
        now = utc_iso()
        with self.database.transaction(immediate=True) as connection:
            connection.execute("DELETE FROM search_cache WHERE expires_at<=?", (now,))
            row = connection.execute(
                "SELECT result FROM search_cache WHERE scope=? AND query_hash=?",
                (scope, query_hash),
            ).fetchone()
            return json.loads(row["result"]) if row else None

    def put_search_cache(self, scope: str, query_hash: str, result: dict[str, Any], ttl_seconds: int = 60) -> None:
        expires = utc_iso(utc_now() + timedelta(seconds=max(5, min(300, ttl_seconds))))
        with self.database.connection() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO search_cache(scope, query_hash, result, expires_at)
                VALUES(?, ?, ?, ?)""",
                (scope, query_hash, json.dumps(result, ensure_ascii=False), expires),
            )
