from __future__ import annotations

import re


class DownloaderError(Exception):
    code = "download_failed"

    def __init__(self, message: str, *, platform: str = "Downloader"):
        super().__init__(message)
        self.platform = platform

    @property
    def user_message(self) -> str:
        return f"❌ {self.platform}: не удалось скачать медиа"


class AuthenticationRequiredError(DownloaderError):
    code = "authentication_required"

    @property
    def user_message(self) -> str:
        return f"🔐 {self.platform} требует обновить авторизацию/cookies."


class MediaUnavailableError(DownloaderError):
    code = "media_unavailable"

    @property
    def user_message(self) -> str:
        return f"❌ {self.platform}: медиа недоступно или удалено."


class DownloadTimeoutError(DownloaderError):
    code = "timeout"

    @property
    def user_message(self) -> str:
        return f"❌ {self.platform}: downloader превысил таймаут."


class BackendUnavailableError(DownloaderError):
    code = "backend_unavailable"


class UnsafeUrlError(DownloaderError):
    code = "unsafe_url"

    @property
    def user_message(self) -> str:
        return "❌ Разрешены только публичные HTTP/HTTPS-ссылки."


class TooManyFilesError(DownloaderError):
    code = "too_many_files"

    @property
    def user_message(self) -> str:
        return f"❌ {self.platform}: в публикации слишком много файлов."


class FileTooLargeError(DownloaderError):
    code = "file_too_large"

    @property
    def user_message(self) -> str:
        return "❌ Файл слишком большой для Telegram. Попробуйте более низкое качество."


_AUTH_MARKERS = (
    "login required",
    "authentication required",
    "sign in",
    "log in",
    "cookies are no longer valid",
    "session has expired",
    "private video",
    "you need to log in",
    "this content is unreachable",
    "checkpoint",
)
_UNAVAILABLE_MARKERS = (
    "video unavailable",
    "media is unavailable",
    "not available",
    "removed",
    "private or removed",
    "unsupported url",
)
_TIMEOUT_MARKERS = ("timed out", "timeout", "deadline exceeded")


def classify_error(message: str, platform: str) -> DownloaderError:
    clean = re.sub(r"(?i)(sessionid|cookie|token)=\S+", r"\1=<redacted>", message)
    lowered = clean.lower()
    if any(marker in lowered for marker in _AUTH_MARKERS):
        return AuthenticationRequiredError(clean, platform=platform)
    if any(marker in lowered for marker in _TIMEOUT_MARKERS):
        return DownloadTimeoutError(clean, platform=platform)
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return MediaUnavailableError(clean, platform=platform)
    return DownloaderError(clean, platform=platform)
