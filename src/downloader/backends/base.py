from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from ..models import MediaMetadata

ProgressCallback = Callable[[str], Awaitable[None]]


class DownloadBackend(Protocol):
    name: str

    async def analyze(self, url: str, platform: str) -> MediaMetadata: ...

    async def download(
        self,
        url: str,
        platform: str,
        choice: str,
        directory: Path,
        progress: ProgressCallback | None = None,
    ) -> list[Path]: ...
