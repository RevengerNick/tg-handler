from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import DownloadJob, FormatChoice, JobStatus


class JobRegistry:
    """Small persistent job registry with atomic callback claiming."""

    def __init__(self, database_path: Path):
        self.database_path = database_path

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        await asyncio.to_thread(self._initialize)
        os.chmod(self.database_path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS download_jobs (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL,
                    source_account_id INTEGER NOT NULL, source_chat_id INTEGER NOT NULL,
                    source_message_id INTEGER NOT NULL, reply_to_message_id INTEGER,
                    platform TEXT NOT NULL, title TEXT, available_formats_json TEXT NOT NULL,
                    selected_format TEXT, status TEXT NOT NULL, created_at REAL NOT NULL,
                    expires_at REAL NOT NULL, control_message_id INTEGER,
                    metadata_json TEXT NOT NULL, error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_download_jobs_status_expiry "
                "ON download_jobs(status, expires_at)"
            )

    @staticmethod
    def make_id() -> str:
        return secrets.token_urlsafe(6).rstrip("-_")[:8]

    async def create(self, job: DownloadJob) -> None:
        await asyncio.to_thread(self._create, job)

    def _create(self, job: DownloadJob) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO download_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.url,
                    job.source_account_id,
                    job.source_chat_id,
                    job.source_message_id,
                    job.reply_to_message_id,
                    job.platform,
                    job.title,
                    json.dumps([asdict(item) for item in job.available_formats]),
                    job.selected_format,
                    job.status.value,
                    job.created_at.timestamp(),
                    job.expires_at.timestamp(),
                    job.control_message_id,
                    json.dumps(job.metadata, ensure_ascii=False),
                    job.error,
                ),
            )

    async def get(self, job_id: str) -> DownloadJob | None:
        return await asyncio.to_thread(self._get, job_id)

    def _get(self, job_id: str) -> DownloadJob | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM download_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    async def set_metadata(
        self,
        job_id: str,
        *,
        title: str,
        platform: str,
        formats: Iterable[FormatChoice],
        metadata: dict,
    ) -> None:
        payload = json.dumps([asdict(item) for item in formats], ensure_ascii=False)
        await asyncio.to_thread(
            self._execute,
            """UPDATE download_jobs SET title=?, platform=?, available_formats_json=?,
               metadata_json=?, status=? WHERE id=? AND status=?""",
            (
                title,
                platform,
                payload,
                json.dumps(metadata, ensure_ascii=False),
                JobStatus.WAITING_QUALITY.value,
                job_id,
                JobStatus.PENDING.value,
            ),
        )

    async def set_control_message(self, job_id: str, message_id: int) -> None:
        await asyncio.to_thread(
            self._execute,
            "UPDATE download_jobs SET control_message_id=? WHERE id=?",
            (message_id, job_id),
        )

    async def claim(self, job_id: str, choice: str) -> DownloadJob | None:
        return await asyncio.to_thread(self._claim, job_id, choice)

    def _claim(self, job_id: str, choice: str) -> DownloadJob | None:
        now = datetime.now(timezone.utc).timestamp()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM download_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] <= now:
                connection.execute(
                    "UPDATE download_jobs SET status=? WHERE id=?",
                    (JobStatus.EXPIRED.value, job_id),
                )
                return None
            if row["status"] != JobStatus.WAITING_QUALITY.value:
                return None
            allowed = {
                item["key"] for item in json.loads(row["available_formats_json"])
            }
            if choice not in allowed:
                return None
            connection.execute(
                "UPDATE download_jobs SET selected_format=?, status=? WHERE id=?",
                (choice, JobStatus.PENDING.value, job_id),
            )
            updated = dict(row)
            updated.update(selected_format=choice, status=JobStatus.PENDING.value)
            return self._from_mapping(updated)

    async def cancel(self, job_id: str) -> DownloadJob | None:
        return await asyncio.to_thread(self._cancel, job_id)

    def _cancel(self, job_id: str) -> DownloadJob | None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM download_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row or row["status"] != JobStatus.WAITING_QUALITY.value:
                return None
            connection.execute(
                "UPDATE download_jobs SET status=? WHERE id=?",
                (JobStatus.CANCELLED.value, job_id),
            )
            updated = dict(row)
            updated["status"] = JobStatus.CANCELLED.value
            return self._from_mapping(updated)

    async def transition(
        self,
        job_id: str,
        expected: Iterable[JobStatus],
        status: JobStatus,
        *,
        error: str | None = None,
    ) -> bool:
        expected_values = tuple(item.value for item in expected)
        if not expected_values:
            return False
        placeholders = ",".join("?" for _ in expected_values)
        changed = await asyncio.to_thread(
            self._execute,
            f"UPDATE download_jobs SET status=?, error=? WHERE id=? AND status IN ({placeholders})",
            (status.value, error, job_id, *expected_values),
        )
        return changed == 1

    async def expire(self) -> list[DownloadJob]:
        return await asyncio.to_thread(self._expire)

    def _expire(self) -> list[DownloadJob]:
        now = datetime.now(timezone.utc).timestamp()
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM download_jobs WHERE status=? AND expires_at<=?",
                (JobStatus.WAITING_QUALITY.value, now),
            ).fetchall()
            connection.execute(
                "UPDATE download_jobs SET status=? WHERE status=? AND expires_at<=?",
                (JobStatus.EXPIRED.value, JobStatus.WAITING_QUALITY.value, now),
            )
        return [self._from_row(row) for row in rows]

    async def recover_interrupted(self) -> int:
        return await asyncio.to_thread(
            self._execute,
            "UPDATE download_jobs SET status=?, error=? WHERE status IN (?, ?, ?)",
            (
                JobStatus.FAILED.value,
                "Application restarted",
                JobStatus.PENDING.value,
                JobStatus.DOWNLOADING.value,
                JobStatus.UPLOADING.value,
            ),
        )

    def _execute(self, query: str, parameters: tuple) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(query, parameters)
            return cursor.rowcount

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> DownloadJob:
        return cls._from_mapping(dict(row))

    @staticmethod
    def _from_mapping(row: dict) -> DownloadJob:
        return DownloadJob(
            id=row["id"],
            url=row["url"],
            source_account_id=row["source_account_id"],
            source_chat_id=row["source_chat_id"],
            source_message_id=row["source_message_id"],
            reply_to_message_id=row["reply_to_message_id"],
            platform=row["platform"],
            title=row["title"],
            available_formats=tuple(
                FormatChoice.from_dict(item)
                for item in json.loads(row["available_formats_json"] or "[]")
            ),
            selected_format=row["selected_format"],
            status=JobStatus(row["status"]),
            created_at=datetime.fromtimestamp(row["created_at"], timezone.utc),
            expires_at=datetime.fromtimestamp(row["expires_at"], timezone.utc),
            control_message_id=row["control_message_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            error=row["error"],
        )
