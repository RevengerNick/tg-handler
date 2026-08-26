from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Database:
    """Small connection-per-operation SQLite wrapper with explicit migrations."""

    def __init__(self, path: str):
        self.path = str(Path(path).resolve())
        self._migration_lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._migration_lock, self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            migration = Path(__file__).parent / "migrations" / "001_initial.sql"
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (utc_iso(),),
            )
            version_two = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version=2"
            ).fetchone()
            if version_two is None:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(messages)").fetchall()
                }
                if "media_metadata_json" not in columns:
                    migration_two = Path(__file__).parent / "migrations" / "002_media_metadata.sql"
                    connection.executescript(migration_two.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES(2, ?)",
                    (utc_iso(),),
                )

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
