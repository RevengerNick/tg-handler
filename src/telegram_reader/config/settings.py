from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from src.config import DATA_DIR


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ReaderSettings:
    enabled: bool
    database_path: str
    api_token: str
    require_cf_access: bool
    cf_client_id: str
    cf_client_secret: str
    body_limit_bytes: int
    rate_limit_per_minute: int
    reservation_ttl_seconds: int
    confirmation_ttl_seconds: int
    max_unread_messages: int
    max_search_candidates: int
    reconcile_min_interval_seconds: int
    max_dialogs_per_reconcile: int
    timezone: str

    @property
    def auth_configured(self) -> bool:
        if not self.api_token:
            return False
        if self.require_cf_access:
            return bool(self.cf_client_id and self.cf_client_secret)
        return True


@lru_cache(maxsize=1)
def get_reader_settings() -> ReaderSettings:
    return ReaderSettings(
        enabled=_bool("TG_READER_ENABLED", True),
        database_path=os.path.abspath(
            os.getenv("TG_READER_DATABASE_PATH", "").strip()
            or os.path.join(DATA_DIR, "telegram_reader.db")
        ),
        api_token=os.getenv("TG_HANDLER_API_TOKEN", "").strip(),
        require_cf_access=_bool("TG_READER_REQUIRE_CF_ACCESS", True),
        cf_client_id=os.getenv("TG_READER_CF_CLIENT_ID", "").strip(),
        cf_client_secret=os.getenv("TG_READER_CF_CLIENT_SECRET", "").strip(),
        body_limit_bytes=_int("TG_READER_BODY_LIMIT_BYTES", 262_144, 16_384, 1_048_576),
        rate_limit_per_minute=_int("TG_READER_RATE_LIMIT_PER_MINUTE", 60, 5, 600),
        reservation_ttl_seconds=_int("TG_READER_RESERVATION_TTL_SECONDS", 180, 30, 900),
        confirmation_ttl_seconds=_int("TG_READER_CONFIRMATION_TTL_SECONDS", 300, 30, 900),
        max_unread_messages=_int("TG_READER_MAX_UNREAD_MESSAGES", 500, 20, 2_000),
        max_search_candidates=_int("TG_READER_MAX_SEARCH_CANDIDATES", 150, 20, 300),
        reconcile_min_interval_seconds=_int(
            "TG_READER_RECONCILE_MIN_INTERVAL_SECONDS", 60, 15, 3_600,
        ),
        max_dialogs_per_reconcile=_int("TG_READER_MAX_DIALOGS", 500, 50, 2_000),
        timezone=os.getenv("TG_READER_TIMEZONE", "Asia/Tashkent").strip() or "Asia/Tashkent",
    )
