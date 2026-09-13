from __future__ import annotations

import logging
from pathlib import Path

from .backends import OmniGetBackend, YtDlpBackend
from .backends.base import ProgressCallback
from .errors import (
    AuthenticationRequiredError,
    DownloaderError,
)
from .files import cleanup_job_directory
from .models import DownloadResult, FormatChoice, MediaMetadata
from .probe import probe_files

logger = logging.getLogger(__name__)


class DownloadService:
    def __init__(
        self, primary: YtDlpBackend, fallback: OmniGetBackend, temporary_root: Path
    ):
        self.primary = primary
        self.fallback = fallback
        self.temporary_root = temporary_root

    def should_fallback(self, error: Exception, platform: str) -> bool:
        return (
            self.fallback.available
            and not isinstance(error, AuthenticationRequiredError)
            and platform in {"Instagram", "TikTok", "X", "Reddit", "Web"}
        )

    async def analyze(self, url: str, platform: str) -> MediaMetadata:
        if platform == "Yandex Music":
            return MediaMetadata(
                url=url,
                platform=platform,
                title="Yandex Music",
                media_type="audio",
                available_formats=(FormatChoice("audio", "🎵 Audio", audio_only=True),),
            )
        try:
            return await self.primary.analyze(url, platform)
        except DownloaderError as error:
            if not self.should_fallback(error, platform):
                raise
            logger.warning("yt-dlp metadata failed for %s; using OmniGet", platform)
            return await self.fallback.analyze(url, platform)

    async def download(
        self,
        *,
        job_id: str,
        url: str,
        platform: str,
        choice: str,
        progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        directory = self.temporary_root / job_id
        backend = self.primary
        if platform == "Yandex Music":
            from src.services.media import download_yandex_track

            directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            raw_paths = await download_yandex_track(url, str(directory))
            paths = [Path(path).resolve() for path in raw_paths]
            if not paths:
                raise DownloaderError(
                    "Yandex Music produced no files", platform=platform
                )
            files = await probe_files(paths)
            return DownloadResult(
                success=True,
                platform=platform,
                title=paths[0].stem,
                files=files,
                backend="yandex-music",
            )
        try:
            paths = await backend.download(url, platform, choice, directory, progress)
        except DownloaderError as error:
            if not self.should_fallback(error, platform):
                raise
            if progress:
                await progress("fallback")
            cleanup_job_directory(directory, self.temporary_root)
            backend = self.fallback
            paths = await backend.download(url, platform, choice, directory, progress)
        files = await probe_files(paths)
        return DownloadResult(
            success=True,
            platform=platform,
            title=paths[0].stem,
            files=files,
            backend=backend.name,
        )

    def cleanup(self, job_id: str) -> None:
        cleanup_job_directory(self.temporary_root / job_id, self.temporary_root)
