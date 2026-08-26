from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValueError("Timestamp must include a UTC offset")
    return value


class UnreadRequest(BaseModel):
    mode: Literal["new_only", "all_unread"] = "new_only"
    since: datetime | None = None
    max_people: int = Field(default=20, ge=1, le=100)
    max_messages_per_person: int = Field(default=20, ge=1, le=100)

    _validate_since = field_validator("since")(_aware)


class SurfaceCommitRequest(BaseModel):
    batch_id: str = Field(min_length=8, max_length=128)


class SearchPrivateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    person: str | None = Field(default=None, max_length=200)
    mode: Literal["exact", "all_terms", "any_terms", "fuzzy"] = "all_terms"
    date_from: datetime | None = None
    date_to: datetime | None = None
    media_type: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=500)

    _validate_dates = field_validator("date_from", "date_to")(_aware)


class SearchChannelsRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["exact", "all_terms", "any_terms", "fuzzy", "semantic"] = "all_terms"
    scope: Literal["joined_channels", "public_global"] = "joined_channels"
    channel_names: list[str] = Field(default_factory=list, max_length=25)
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = Field(default=20, ge=1, le=150)
    cursor: str | None = Field(default=None, max_length=500)
    include_context: bool = False
    semantic_top_k: int = Field(default=20, ge=1, le=50)
    confirm_public_global: bool = False

    _validate_dates = field_validator("date_from", "date_to")(_aware)

    @field_validator("channel_names")
    @classmethod
    def validate_channel_names(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]


class ContextRequest(BaseModel):
    peer_id: int
    message_id: int = Field(gt=0)
    before: int = Field(default=3, ge=0, le=10)
    after: int = Field(default=3, ge=0, le=10)


class PrepareMarkReadRequest(BaseModel):
    person: str = Field(min_length=1, max_length=200)
    max_message_id: int | None = Field(default=None, gt=0)


class ConfirmMarkReadRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=256)


def as_utc_iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None
