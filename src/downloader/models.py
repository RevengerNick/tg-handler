from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    WAITING_QUALITY = "waiting_quality"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class FormatChoice:
    key: str
    label: str
    height: int | None = None
    audio_only: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FormatChoice:
        return cls(**value)


@dataclass(frozen=True)
class MediaMetadata:
    url: str
    platform: str
    title: str
    author: str | None = None
    duration: float | None = None
    media_type: str = "video"
    entry_count: int = 1
    thumbnail_url: str | None = None
    available_formats: tuple[FormatChoice, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["available_formats"] = [asdict(item) for item in self.available_formats]
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MediaMetadata:
        data = dict(value)
        data["available_formats"] = tuple(
            FormatChoice.from_dict(item) for item in data.get("available_formats", [])
        )
        return cls(**data)


@dataclass
class DownloadJob:
    id: str
    url: str
    source_account_id: int
    source_chat_id: int
    source_message_id: int
    reply_to_message_id: int | None
    platform: str
    status: JobStatus
    created_at: datetime
    expires_at: datetime
    title: str | None = None
    available_formats: tuple[FormatChoice, ...] = ()
    selected_format: str | None = None
    control_message_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
    media_type: str
    size: int
    duration: float | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class DownloadResult:
    success: bool
    platform: str
    title: str
    files: tuple[DownloadedFile, ...]
    backend: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
