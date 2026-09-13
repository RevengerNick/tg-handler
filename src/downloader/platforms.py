from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import UnsafeUrlError

_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_TRAILING = ".,;:!?)]}>\"'"


def extract_url(text: str | None) -> str | None:
    if not text:
        return None
    match = _URL_RE.search(text.replace("\\://", "://"))
    return match.group(0).rstrip(_TRAILING) if match else None


def validate_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("Unsupported URL scheme")

    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrlError("Local host is not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise UnsafeUrlError("Private IP address is not allowed")

    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path, parsed.query, "")
    )


def detect_platform(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()

    def is_domain(domain: str) -> bool:
        return host == domain or host.endswith(f".{domain}")

    if (
        host == "youtu.be"
        or is_domain("youtube.com")
        or is_domain("youtube-nocookie.com")
    ):
        return "YouTube"
    if is_domain("instagram.com"):
        return "Instagram"
    if is_domain("twitter.com") or is_domain("x.com"):
        return "X"
    if is_domain("tiktok.com"):
        return "TikTok"
    if is_domain("reddit.com") or host == "redd.it":
        return "Reddit"
    if is_domain("music.yandex.ru") or is_domain("music.yandex.com"):
        return "Yandex Music"
    return "Web"


def cookie_file_for(platform: str, cookies_dir: Path) -> Path | None:
    filename = {
        "Instagram": "instagram.txt",
        "YouTube": "youtube.txt",
        "X": "x.txt",
    }.get(platform)
    if not filename:
        return None
    path = cookies_dir / filename
    return path if path.is_file() else None
