from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .models import DownloadedFile
from .process import run_process


async def probe_file(path: Path) -> DownloadedFile:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        result = await run_process(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            timeout=30,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except (asyncio.TimeoutError, json.JSONDecodeError, FileNotFoundError):
        payload = {}

    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    extension = path.suffix.lower()
    if video and extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        media_type = "video"
    elif audio:
        media_type = "audio"
    elif extension in {".jpg", ".jpeg", ".png", ".webp"}:
        media_type = "image"
    else:
        media_type = "document"
    duration_value = (payload.get("format") or {}).get("duration")
    try:
        duration = float(duration_value) if duration_value is not None else None
    except (TypeError, ValueError):
        duration = None
    return DownloadedFile(
        path=path,
        media_type=media_type,
        size=path.stat().st_size,
        duration=duration,
        width=int(video["width"]) if video and video.get("width") else None,
        height=int(video["height"]) if video and video.get("height") else None,
    )


async def probe_files(paths: list[Path]) -> tuple[DownloadedFile, ...]:
    return tuple(await asyncio.gather(*(probe_file(path) for path in paths)))
