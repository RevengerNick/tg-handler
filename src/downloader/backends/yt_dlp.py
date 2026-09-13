from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from ..errors import (
    DownloaderError,
    DownloadTimeoutError,
    TooManyFilesError,
    classify_error,
)
from ..files import find_downloaded_paths
from ..formats import format_selector, normalize_yt_dlp_metadata
from ..models import MediaMetadata
from ..platforms import cookie_file_for
from ..process import run_process
from .base import ProgressCallback


class YtDlpBackend:
    name = "yt-dlp"

    def __init__(
        self,
        *,
        cookies_dir: Path,
        metadata_timeout: int,
        download_timeout: int,
        max_files: int,
    ):
        self.cookies_dir = cookies_dir
        self.metadata_timeout = metadata_timeout
        self.download_timeout = download_timeout
        self.max_files = max_files

    def _common(self, platform: str) -> list[str]:
        args = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-color"]
        cookie = cookie_file_for(platform, self.cookies_dir)
        if cookie:
            args.extend(["--cookies", str(cookie)])
        return args

    async def analyze(self, url: str, platform: str) -> MediaMetadata:
        args = self._common(platform)
        args.extend(
            [
                "--dump-single-json",
                "--skip-download",
                "--playlist-end",
                str(self.max_files),
            ]
        )
        if platform not in {"Instagram"}:
            args.append("--no-playlist")
        args.append(url)
        try:
            result = await run_process(args, timeout=self.metadata_timeout)
        except asyncio.TimeoutError as error:
            raise DownloadTimeoutError("Metadata timeout", platform=platform) from error
        if result.returncode:
            raise classify_error(result.stderr or result.stdout, platform)
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise DownloaderError(
                "yt-dlp returned invalid metadata", platform=platform
            ) from error
        return normalize_yt_dlp_metadata(info, url, platform)

    async def download(
        self,
        url: str,
        platform: str,
        choice: str,
        directory: Path,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        args = self._common(platform)
        args.extend(
            [
                "--newline",
                "--progress",
                "--playlist-end",
                str(self.max_files),
                "--windows-filenames",
                "--merge-output-format",
                "mp4",
                "-o",
                str(directory / "%(title).150B [%(id)s].%(ext)s"),
            ]
        )
        if platform not in {"Instagram"}:
            args.append("--no-playlist")
        if choice == "audio":
            args.extend(
                [
                    "-f",
                    format_selector(choice),
                    "-x",
                    "--audio-format",
                    "mp3",
                    "--audio-quality",
                    "192K",
                ]
            )
        else:
            args.extend(["-f", format_selector(choice)])
        args.append(url)

        async def on_line(line: str) -> None:
            if progress and line.startswith(("[download]", "[Merger]")):
                await progress(line)

        try:
            result = await run_process(
                args, timeout=self.download_timeout, on_stdout=on_line
            )
        except asyncio.TimeoutError as error:
            raise DownloadTimeoutError("Download timeout", platform=platform) from error
        if result.returncode:
            raise classify_error(result.stderr or result.stdout, platform)
        paths = find_downloaded_paths(directory)
        if not paths:
            raise DownloaderError("Downloader produced no files", platform=platform)
        if len(paths) > self.max_files:
            raise TooManyFilesError(
                f"Too many downloaded files: {len(paths)}", platform=platform
            )
        return paths
