from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from pyrogram import Client, enums
from pyrogram.errors import RPCError

from .errors import FileTooLargeError
from .models import DownloadJob, DownloadResult

StatusCallback = Callable[[str, float | None], Awaitable[None]]


class TelegramUploader:
    def __init__(self, *, max_bytes: int = 4_000_000_000):
        self.max_bytes = max_bytes

    async def upload(
        self,
        client: Client,
        job: DownloadJob,
        result: DownloadResult,
        status: StatusCallback,
    ) -> None:
        for index, item in enumerate(result.files, start=1):
            if not item.path.is_file() or item.path.stat().st_size != item.size:
                raise FileNotFoundError(item.path)
            if item.size > self.max_bytes:
                raise FileTooLargeError(str(item.path), platform=result.platform)
            last_update = 0.0

            async def progress(current: int, total: int) -> None:
                nonlocal last_update
                now = time.monotonic()
                if total and now - last_update >= 2.5:
                    last_update = now
                    await status("uploading", current * 100 / total)

            caption = f"✅ {result.title}"
            if len(result.files) > 1:
                caption += f" ({index}/{len(result.files)})"
            common = {
                "chat_id": job.source_chat_id,
                "caption": caption[:1024],
                "reply_to_message_id": job.reply_to_message_id,
                "progress": progress,
                "parse_mode": enums.ParseMode.DISABLED,
            }
            if item.media_type == "video":
                try:
                    await client.send_video(
                        video=str(item.path),
                        duration=int(item.duration or 0) or None,
                        width=item.width,
                        height=item.height,
                        supports_streaming=True,
                        **common,
                    )
                except RPCError:
                    await client.send_document(document=str(item.path), **common)
            elif item.media_type == "audio":
                await client.send_audio(
                    audio=str(item.path),
                    duration=int(item.duration or 0) or None,
                    **common,
                )
            elif item.media_type == "image":
                await client.send_photo(photo=str(item.path), **common)
            else:
                await client.send_document(document=str(item.path), **common)
