from __future__ import annotations

from pyrogram import Client, filters

from src.downloader import get_downloader_runtime
from src.downloader.errors import DownloaderError
from src.downloader.platforms import extract_url

_COMMANDS = ["dl", "дл", "скачать", "dl0", "dlo"]
_ALIASES = {"0": "best", "1": "480", "2": "audio", "low": "480"}
_DIRECT = {"best", "1080", "720", "480", "360", "audio"}


def parse_download_request(message) -> tuple[str | None, str | None]:
    command = (message.command[0] if message.command else "dl").lower()
    parts = (message.text or "").split(maxsplit=2)
    choice: str | None = "480" if command in {"dl0", "dlo"} else None
    own_text = parts[1:] if len(parts) > 1 else []
    if own_text:
        first = own_text[0].lower()
        mapped = _ALIASES.get(first, first)
        if mapped in _DIRECT:
            choice = mapped
    url = extract_url(message.text)
    if not url and message.reply_to_message:
        reply = message.reply_to_message
        if not (reply.video or reply.document or reply.audio):
            url = extract_url(reply.text or reply.caption)
    return url, choice


@Client.on_message(filters.me & filters.command(_COMMANDS, prefixes="."))
async def download_handler(client, message):
    url, choice = parse_download_request(message)
    if not url:
        return await message.edit(
            "❌ Ссылка не найдена. Используйте `.dl URL`, `.dlo URL` или ответьте `.dl` на сообщение со ссылкой."
        )
    try:
        await get_downloader_runtime().submit(client, message, url, choice)
    except DownloaderError as error:
        await message.edit(error.user_message)
