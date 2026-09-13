from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ..errors import (
    BackendUnavailableError,
    DownloaderError,
    DownloadTimeoutError,
    TooManyFilesError,
    classify_error,
)
from ..files import find_downloaded_paths
from ..formats import normalize_omniget_metadata
from ..models import MediaMetadata
from ..platforms import cookie_file_for
from ..process import run_process
from .base import ProgressCallback


def parse_omniget_json(output: str) -> list[dict]:
    values: list[dict] = []
    for line in output.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            values.append(item)
    return values


class OmniGetBackend:
    name = "OmniGet"

    def __init__(
        self,
        *,
        executable: str,
        cookies_dir: Path,
        metadata_timeout: int,
        download_timeout: int,
        max_files: int,
    ):
        self.executable = executable
        self.cookies_dir = cookies_dir
        self.metadata_timeout = metadata_timeout
        self.download_timeout = download_timeout
        self.max_files = max_files

    @property
    def available(self) -> bool:
        return Path(self.executable).is_file() and os.access(self.executable, os.X_OK)

    def _ensure_available(self) -> None:
        if not self.available:
            raise BackendUnavailableError("OmniGet CLI is not installed")

    async def _import_cookie(self, platform: str, environment: dict[str, str]) -> None:
        cookie = cookie_file_for(platform, self.cookies_dir)
        if not cookie:
            return
        result = await run_process(
            [
                self.executable,
                "--json",
                "import-cookies",
                str(cookie),
                "--name",
                platform.lower().replace(" ", "-"),
            ],
            timeout=self.metadata_timeout,
            environment=environment,
        )
        if result.returncode:
            raise classify_error(result.stderr or result.stdout, platform)

    @staticmethod
    def _environment(directory: Path) -> dict[str, str]:
        environment = dict(os.environ)
        environment["XDG_DATA_HOME"] = str(directory / ".omniget")
        return environment

    async def analyze(self, url: str, platform: str) -> MediaMetadata:
        self._ensure_available()
        state_dir = self.cookies_dir.parent / "omniget"
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        environment = self._environment(state_dir)
        await self._import_cookie(platform, environment)
        try:
            result = await run_process(
                [self.executable, "--json", "info", url],
                timeout=self.metadata_timeout,
                environment=environment,
            )
        except asyncio.TimeoutError as error:
            raise DownloadTimeoutError(
                "OmniGet metadata timeout", platform=platform
            ) from error
        if result.returncode:
            raise classify_error(result.stderr or result.stdout, platform)
        values = parse_omniget_json(result.stdout)
        if not values:
            raise DownloaderError(
                "OmniGet returned invalid metadata", platform=platform
            )
        return normalize_omniget_metadata(values[-1], url)

    async def download(
        self,
        url: str,
        platform: str,
        choice: str,
        directory: Path,
        progress: ProgressCallback | None = None,
    ) -> list[Path]:
        self._ensure_available()
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        environment = self._environment(directory)
        await self._import_cookie(platform, environment)
        args = [
            self.executable,
            "--json",
            "download",
            "--output",
            str(directory),
            "--format",
            "mp4",
        ]
        if choice == "audio":
            args.append("--audio-only")
        elif choice.isdigit():
            args.extend(["--quality", choice])
        args.append(url)

        async def on_line(line: str) -> None:
            if progress:
                values = parse_omniget_json(line)
                if values and values[-1].get("type") == "progress":
                    await progress(line)

        try:
            result = await run_process(
                args,
                timeout=self.download_timeout,
                environment=environment,
                on_stdout=on_line,
            )
        except asyncio.TimeoutError as error:
            raise DownloadTimeoutError(
                "OmniGet download timeout", platform=platform
            ) from error
        if result.returncode:
            raise classify_error(result.stderr or result.stdout, platform)
        paths = find_downloaded_paths(directory)
        if not paths:
            raise DownloaderError("OmniGet produced no files", platform=platform)
        if len(paths) > self.max_files:
            raise TooManyFilesError(
                f"Too many downloaded files: {len(paths)}", platform=platform
            )
        return paths
