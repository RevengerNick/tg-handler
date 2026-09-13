from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import CallbackQuery
from pyrogram import Client

from .backends import OmniGetBackend, YtDlpBackend
from .config import DownloaderSettings
from .control_bot import DownloadControlBot
from .errors import DownloaderError
from .messages import source_status
from .models import DownloadJob, JobStatus
from .platforms import detect_platform, validate_url
from .registry import JobRegistry
from .service import DownloadService
from .uploader import TelegramUploader

logger = logging.getLogger(__name__)
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")


class DownloaderRuntime:
    def __init__(self, settings: DownloaderSettings | None = None):
        self.settings = settings or DownloaderSettings.from_env()
        self.registry = JobRegistry(self.settings.database_path)
        primary = YtDlpBackend(
            cookies_dir=self.settings.cookies_dir,
            metadata_timeout=self.settings.metadata_timeout_seconds,
            download_timeout=self.settings.download_timeout_seconds,
            max_files=self.settings.max_files,
        )
        fallback = OmniGetBackend(
            executable=self.settings.omniget_path,
            cookies_dir=self.settings.cookies_dir,
            metadata_timeout=self.settings.metadata_timeout_seconds,
            download_timeout=self.settings.download_timeout_seconds,
            max_files=self.settings.max_files,
        )
        self.service = DownloadService(primary, fallback, self.settings.temporary_root)
        self.uploader = TelegramUploader()
        self.control: DownloadControlBot | None = None
        self.clients: dict[int, Client] = {}
        self.semaphore = asyncio.Semaphore(self.settings.max_concurrent)
        self.tasks: set[asyncio.Task] = set()
        self.last_progress_update: dict[str, float] = {}
        self.expiry_task: asyncio.Task | None = None
        self.started = False

    async def start(self, clients: list[Client]) -> None:
        if self.started:
            return
        self.settings.ensure_directories()
        await self.registry.initialize()
        await self.registry.recover_interrupted()
        for orphan in self.settings.temporary_root.iterdir():
            if orphan.is_dir():
                with contextlib.suppress(Exception):
                    self.service.cleanup(orphan.name)
        for client in clients:
            await self.register_client(client)
        if self.settings.control_enabled:
            control = DownloadControlBot(
                self.settings.bot_token,
                self.settings.control_user_id,
                self.handle_callback,
            )
            try:
                await control.start()
            except TelegramAPIError as error:
                logger.error(
                    "Download control bot could not start: %s", type(error).__name__
                )
                await control.stop()
                print("⚠️ Download control bot отключён: проверьте token и user ID.")
            else:
                self.control = control
                print("🎛 Download control bot запущен.")
        else:
            print(
                "ℹ️ Download control bot отключён: задайте DOWNLOAD_BOT_TOKEN и DOWNLOAD_CONTROL_USER_ID."
            )
        self.expiry_task = asyncio.create_task(
            self._expiry_loop(), name="download-job-expiry"
        )
        self.started = True

    async def register_client(self, client: Client) -> None:
        """Make a started/reconnected user session available for source uploads."""
        me = await client.get_me()
        self.clients[int(me.id)] = client

    def unregister_client(self, client: Client) -> None:
        for account_id, registered in tuple(self.clients.items()):
            if registered is client:
                self.clients.pop(account_id, None)

    async def stop(self) -> None:
        if self.expiry_task:
            self.expiry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.expiry_task
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.control:
            await self.control.stop()
        self.started = False

    async def submit(
        self, client: Client, message, url: str, choice: str | None = None
    ) -> DownloadJob | None:
        url = validate_url(url)
        me = await client.get_me()
        now = datetime.now(timezone.utc)
        job = DownloadJob(
            id=self.registry.make_id(),
            url=url,
            source_account_id=int(me.id),
            source_chat_id=int(message.chat.id),
            source_message_id=int(message.id),
            reply_to_message_id=(
                int(message.reply_to_message.id) if message.reply_to_message else None
            ),
            platform=detect_platform(url),
            status=JobStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.job_ttl_seconds),
            selected_format=choice,
        )
        await self.registry.create(job)
        if choice:
            await self._edit_source(job, source_status("queued"))
            self._spawn(self._execute(job))
            return job
        if not self.control:
            await self._edit_source(
                job,
                "❌ Интерактивный режим не настроен. Используйте `.dlo URL` или добавьте DOWNLOAD_BOT_TOKEN.",
            )
            await self.registry.transition(
                job.id,
                [JobStatus.PENDING],
                JobStatus.FAILED,
                error="Control bot is disabled",
            )
            return None
        await self._edit_source(job, source_status("analyzing"))
        try:
            metadata = await self.service.analyze(job.url, job.platform)
            await self.registry.set_metadata(
                job.id,
                title=metadata.title,
                platform=metadata.platform,
                formats=metadata.available_formats,
                metadata=metadata.to_dict(),
            )
            refreshed = await self.registry.get(job.id)
            if not refreshed:
                return None
            message_id = await self.control.send_job(refreshed, metadata)
            await self.registry.set_control_message(job.id, message_id)
            await self._edit_source(job, source_status("waiting"))
            return refreshed
        except TelegramForbiddenError:
            await self.registry.transition(
                job.id,
                [JobStatus.PENDING, JobStatus.WAITING_QUALITY],
                JobStatus.FAILED,
                error="Control user has not started the companion bot",
            )
            await self._edit_source(
                job, "❌ Сначала отправьте `/start` служебному downloader-боту."
            )
        except DownloaderError as error:
            await self.registry.transition(
                job.id, [JobStatus.PENDING], JobStatus.FAILED, error=str(error)
            )
            await self._edit_source(job, error.user_message)
        except Exception as error:
            logger.exception("Download metadata failed for job %s", job.id)
            await self.registry.transition(
                job.id,
                [JobStatus.PENDING],
                JobStatus.FAILED,
                error=type(error).__name__,
            )
            await self._edit_source(job, "❌ Не удалось проанализировать ссылку.")
        return None

    async def handle_callback(
        self, callback: CallbackQuery, job_id: str, choice: str
    ) -> None:
        if choice == "cancel":
            job = await self.registry.cancel(job_id)
            if not job:
                await callback.answer("Запрос уже истёк", show_alert=True)
                return
            await callback.answer("Отменено")
            await self._edit_source(job, "❌ Скачивание отменено.")
            if callback.message:
                with contextlib.suppress(Exception):
                    await callback.message.delete()
            return

        job = await self.registry.claim(job_id, choice)
        if not job:
            await callback.answer("Запрос уже истёк или запущен", show_alert=True)
            return
        await callback.answer("Скачивание запущено")
        if callback.message:
            with contextlib.suppress(Exception):
                await callback.message.edit_text(
                    source_status("downloading", quality=choice), reply_markup=None
                )
        self._spawn(self._execute(job))

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _execute(self, job: DownloadJob) -> None:
        async with self.semaphore:
            if not await self.registry.transition(
                job.id, [JobStatus.PENDING], JobStatus.DOWNLOADING
            ):
                return
            await self._edit_source(
                job, source_status("downloading", quality=job.selected_format)
            )
            try:

                async def download_progress(value: str) -> None:
                    if value == "fallback":
                        await self._edit_source(job, source_status("fallback"))
                        return
                    match = _PERCENT_RE.search(value)
                    if match:
                        now = time.monotonic()
                        if now - self.last_progress_update.get(job.id, 0) < 2.5:
                            return
                        self.last_progress_update[job.id] = now
                        await self._edit_source(
                            job,
                            f"📥 Скачиваю {job.selected_format or 'best'}… {match.group(1)}%",
                        )

                result = await self.service.download(
                    job_id=job.id,
                    url=job.url,
                    platform=job.platform,
                    choice=job.selected_format or "best",
                    progress=download_progress,
                )
                await self.registry.transition(
                    job.id, [JobStatus.DOWNLOADING], JobStatus.UPLOADING
                )

                async def upload_status(state: str, percent: float | None) -> None:
                    await self._edit_source(job, source_status(state, percent=percent))

                client = self.clients.get(job.source_account_id)
                if not client:
                    raise RuntimeError("Source Telegram account is not connected")
                await self.uploader.upload(client, job, result, upload_status)
                await self.registry.transition(
                    job.id, [JobStatus.UPLOADING], JobStatus.COMPLETED
                )
                await self._edit_source(job, source_status("done"))
                await self._finish_control(job, "✅ Готово")
            except DownloaderError as error:
                logger.exception("Download job %s failed", job.id)
                await self.registry.transition(
                    job.id,
                    [JobStatus.DOWNLOADING, JobStatus.UPLOADING],
                    JobStatus.FAILED,
                    error=str(error),
                )
                await self._edit_source(job, error.user_message)
                await self._finish_control(job, error.user_message)
            except asyncio.CancelledError:
                await self.registry.transition(
                    job.id,
                    [JobStatus.DOWNLOADING, JobStatus.UPLOADING],
                    JobStatus.FAILED,
                    error="Application stopped",
                )
                raise
            except Exception as error:
                logger.exception("Download job %s failed", job.id)
                await self.registry.transition(
                    job.id,
                    [JobStatus.DOWNLOADING, JobStatus.UPLOADING],
                    JobStatus.FAILED,
                    error=type(error).__name__,
                )
                await self._edit_source(job, "❌ Downloader: внутренняя ошибка.")
                await self._finish_control(job, "❌ Ошибка скачивания")
            finally:
                self.last_progress_update.pop(job.id, None)
                with contextlib.suppress(Exception):
                    self.service.cleanup(job.id)

    async def _edit_source(self, job: DownloadJob, text: str) -> None:
        client = self.clients.get(job.source_account_id)
        if client:
            with contextlib.suppress(Exception):
                await client.edit_message_text(
                    job.source_chat_id, job.source_message_id, text
                )

    async def _finish_control(self, job: DownloadJob, text: str) -> None:
        if not self.control or not job.control_message_id:
            return
        with contextlib.suppress(Exception):
            await self.control.bot.edit_message_text(
                text,
                self.settings.control_user_id,
                job.control_message_id,
                reply_markup=None,
            )
        self._spawn(
            self.control.delete_later(
                self.settings.control_user_id, job.control_message_id
            )
        )

    async def _expiry_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            for job in await self.registry.expire():
                await self._edit_source(job, "⌛ Запрос скачивания истёк.")
                await self._finish_control(job, "⌛ Запрос истёк")


_runtime: DownloaderRuntime | None = None


def get_downloader_runtime() -> DownloaderRuntime:
    global _runtime
    if _runtime is None:
        _runtime = DownloaderRuntime()
    return _runtime
