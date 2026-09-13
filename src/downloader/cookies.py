from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class CookieStatus:
    platform: str
    path: Path
    exists: bool
    modified_at: datetime | None
    valid_rows: int = 0
    expired_rows: int = 0


class CookieStore:
    platforms = ("Instagram", "YouTube", "X")

    def __init__(self, directory: Path):
        self.directory = directory

    def path_for(self, platform: str) -> Path:
        filename = {
            "instagram": "instagram.txt",
            "youtube": "youtube.txt",
            "x": "x.txt",
        }.get(platform.lower())
        if not filename:
            raise ValueError("Поддерживаются: instagram, youtube, x")
        return self.directory / filename

    def inspect(self, platform: str) -> CookieStatus:
        path = self.path_for(platform)
        if not path.is_file():
            return CookieStatus(platform.title(), path, False, None)
        valid = expired = 0
        now = int(time.time())
        with path.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                stripped = line.strip()
                if stripped.startswith("#HttpOnly_"):
                    line = line.replace("#HttpOnly_", "", 1)
                elif not stripped or stripped.startswith("#"):
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 7:
                    continue
                try:
                    expires = int(fields[4])
                except ValueError:
                    continue
                if expires and expires <= now:
                    expired += 1
                else:
                    valid += 1
        return CookieStatus(
            platform.title(),
            path,
            True,
            datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
            valid,
            expired,
        )

    def inspect_all(self) -> tuple[CookieStatus, ...]:
        return tuple(self.inspect(platform) for platform in self.platforms)

    def validate_for(self, platform: str) -> tuple[bool, str]:
        status = self.inspect(platform)
        if not status.exists:
            return False, f"Файл {status.path.name} не найден"
        if not status.valid_rows:
            return False, "Нет действующих строк Netscape cookies.txt"
        return True, (
            f"Формат корректен: действующих записей {status.valid_rows}, "
            f"истёкших {status.expired_rows}. Для полной проверки добавьте URL."
        )
