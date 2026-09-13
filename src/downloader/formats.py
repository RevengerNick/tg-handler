from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import FormatChoice, MediaMetadata

_QUALITY_LEVELS = (2160, 1440, 1080, 720, 480, 360)


def _entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    values = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
    return values or [info]


def _formats(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        value
        for item in items
        for value in (item.get("formats") or [])
        if isinstance(value, dict)
    ]


def normalize_yt_dlp_metadata(
    info: dict[str, Any], url: str, platform: str
) -> MediaMetadata:
    entries = _entries(info)
    formats = _formats(entries[:1])
    title = str(info.get("title") or entries[0].get("title") or "Media")[:300]
    author = info.get("uploader") or info.get("channel") or entries[0].get("uploader")
    duration = info.get("duration") or entries[0].get("duration")
    thumbnail = info.get("thumbnail") or entries[0].get("thumbnail")
    heights = {
        int(value["height"])
        for value in formats
        if value.get("height") and value.get("vcodec") != "none"
    }
    has_video = any(value.get("vcodec") not in (None, "none") for value in formats)
    has_audio = any(value.get("acodec") not in (None, "none") for value in formats)
    ext = str(info.get("ext") or entries[0].get("ext") or "")
    is_collection = len(entries) > 1 or info.get("_type") in {"playlist", "multi_video"}

    if is_collection:
        media_type = "collection"
    elif has_video or ext in {"mp4", "webm", "mkv", "mov"}:
        media_type = "video"
    elif has_audio or ext in {"mp3", "m4a", "ogg", "opus", "wav"}:
        media_type = "audio"
    else:
        media_type = "image"

    choices: list[FormatChoice] = []
    simplified = (
        platform in {"Instagram", "TikTok"} or is_collection or len(heights) <= 1
    )
    if media_type == "audio":
        choices.append(FormatChoice("audio", "🎵 Audio", audio_only=True))
    elif media_type in {"video", "collection"}:
        choices.append(FormatChoice("best", "⬇️ Скачать" if simplified else "Original"))
        if not simplified:
            for height in _QUALITY_LEVELS:
                if height in heights:
                    choices.append(
                        FormatChoice(str(height), f"{height}p", height=height)
                    )
        if has_audio or media_type == "collection":
            choices.append(FormatChoice("audio", "🎵 Audio", audio_only=True))
    else:
        choices.append(FormatChoice("best", "⬇️ Скачать"))

    return MediaMetadata(
        url=url,
        platform=platform,
        title=title,
        author=str(author)[:200] if author else None,
        duration=float(duration) if duration is not None else None,
        media_type=media_type,
        entry_count=len(entries),
        thumbnail_url=str(thumbnail) if thumbnail else None,
        available_formats=tuple(choices),
        raw={"extractor": info.get("extractor"), "id": info.get("id")},
    )


def normalize_omniget_metadata(info: dict[str, Any], url: str) -> MediaMetadata:
    platform = str(info.get("platform") or "Web").title()
    media_type = str(info.get("media_type") or "video").lower()
    choices = [FormatChoice("best", "⬇️ Скачать")]
    if media_type in {"video", "carousel", "playlist"}:
        choices.append(FormatChoice("audio", "🎵 Audio", audio_only=True))
    return MediaMetadata(
        url=url,
        platform=platform,
        title=str(info.get("title") or "Media")[:300],
        author=str(info.get("uploader") or "")[:200] or None,
        duration=float(info.get("duration") or 0) or None,
        media_type="collection"
        if media_type in {"carousel", "playlist"}
        else media_type,
        entry_count=1,
        thumbnail_url=info.get("thumbnail_url"),
        available_formats=tuple(choices),
        raw={"format_count": info.get("format_count")},
    )


def format_selector(choice: str) -> str:
    if choice == "audio":
        return "bestaudio/best"
    if choice == "best":
        return (
            "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"
        )
    if choice.isdigit():
        height = int(choice)
        return (
            f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best"
        )
    raise ValueError(f"Unsupported format choice: {choice}")
