from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.config import DATA_DIR, TEMP_DIR


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class DownloaderSettings:
    bot_token: str
    control_user_id: int
    database_path: Path
    cookies_dir: Path
    temporary_root: Path
    job_ttl_seconds: int
    max_concurrent: int
    max_files: int
    metadata_timeout_seconds: int
    download_timeout_seconds: int
    omniget_path: str

    @property
    def control_enabled(self) -> bool:
        return bool(self.bot_token and self.control_user_id > 0)

    @classmethod
    def from_env(cls) -> DownloaderSettings:
        try:
            control_user_id = int(os.getenv("DOWNLOAD_CONTROL_USER_ID", "0"))
        except ValueError:
            control_user_id = 0

        return cls(
            bot_token=os.getenv("DOWNLOAD_BOT_TOKEN", "").strip(),
            control_user_id=control_user_id,
            database_path=Path(
                os.getenv(
                    "DOWNLOAD_JOB_DATABASE_PATH", Path(DATA_DIR, "download_jobs.db")
                )
            ).resolve(),
            cookies_dir=Path(
                os.getenv("DOWNLOAD_COOKIES_DIR", Path(DATA_DIR, "cookies"))
            ).resolve(),
            temporary_root=Path(TEMP_DIR, "downloads").resolve(),
            job_ttl_seconds=_integer("DOWNLOAD_JOB_TTL_SECONDS", 1200, 300, 3600),
            max_concurrent=_integer("DOWNLOAD_MAX_CONCURRENT", 1, 1, 2),
            max_files=_integer("DOWNLOAD_MAX_FILES", 10, 1, 20),
            metadata_timeout_seconds=_integer(
                "DOWNLOAD_METADATA_TIMEOUT_SECONDS", 60, 10, 300
            ),
            download_timeout_seconds=_integer(
                "DOWNLOAD_TIMEOUT_SECONDS", 1800, 60, 7200
            ),
            omniget_path=os.getenv("OMNIGET_PATH", "/usr/local/bin/omniget").strip(),
        )

    def ensure_directories(self) -> None:
        for directory in (self.cookies_dir, self.temporary_root):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
