from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .callbacks import CallbackCodec
from .messages import control_card
from .models import DownloadJob, MediaMetadata

CallbackHandler = Callable[[CallbackQuery, str, str], Awaitable[None]]


class DownloadControlBot:
    def __init__(
        self, token: str, control_user_id: int, callback_handler: CallbackHandler
    ):
        self.control_user_id = control_user_id
        self.bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dispatcher = Dispatcher()
        self.callback_handler = callback_handler
        self.task: asyncio.Task | None = None
        self.dispatcher.callback_query.register(
            self._callback, F.data.startswith("dl:")
        )

    async def start(self) -> None:
        # Validate configuration before detaching polling into the background.
        await self.bot.get_me()
        self.task = asyncio.create_task(
            self.dispatcher.start_polling(self.bot, handle_signals=False),
            name="download-control-bot",
        )

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.bot.session.close()

    async def send_job(self, job: DownloadJob, metadata: MediaMetadata) -> int:
        buttons = [
            InlineKeyboardButton(
                text=choice.label,
                callback_data=CallbackCodec.encode(job.id, choice.key),
            )
            for choice in metadata.available_formats
        ]
        rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=CallbackCodec.encode(job.id, "cancel"),
                )
            ]
        )
        message = await self.bot.send_message(
            self.control_user_id,
            control_card(metadata),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return message.message_id

    async def _callback(self, callback: CallbackQuery) -> None:
        if callback.from_user.id != self.control_user_id:
            await callback.answer("Недоступно", show_alert=True)
            return
        try:
            job_id, choice = CallbackCodec.decode(callback.data or "")
        except ValueError:
            await callback.answer("Некорректный запрос", show_alert=True)
            return
        await self.callback_handler(callback, job_id, choice)

    async def delete_later(
        self, chat_id: int, message_id: int, delay: float = 4
    ) -> None:
        await asyncio.sleep(delay)
        with contextlib.suppress(Exception):
            await self.bot.delete_message(chat_id, message_id)
