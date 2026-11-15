import asyncio
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from src.downloader.backends.omniget import parse_omniget_json
from src.downloader.callbacks import CallbackCodec
from src.downloader.config import DownloaderSettings
from src.downloader.cookies import CookieStore
from src.downloader.files import cleanup_job_directory, find_downloaded_paths
from src.downloader.formats import format_selector, normalize_yt_dlp_metadata
from src.downloader.models import DownloadJob, FormatChoice, JobStatus, MediaMetadata
from src.downloader.platforms import cookie_file_for, detect_platform, extract_url
from src.downloader.registry import JobRegistry
from src.downloader.runtime import DownloaderRuntime
from src.downloader.service import DownloadService
from src.handlers.downloads import parse_download_request


class DownloaderPureTests(unittest.TestCase):
    def test_url_and_platform_detection(self):
        self.assertEqual(
            "https://youtu.be/abc", extract_url(r"go https\://youtu.be/abc.")
        )
        self.assertEqual("YouTube", detect_platform("https://m.youtube.com/watch?v=1"))
        self.assertEqual("Instagram", detect_platform("https://www.instagram.com/p/1"))
        self.assertEqual("Web", detect_platform("https://evilinstagram.com/p/1"))

    def test_yandex_music_domains(self):
        for domain in ("music.yandex.ru", "music.yandex.com", "music.yandex.uz"):
            with self.subTest(domain=domain):
                url = f"https://{domain}/album/123/track/456"
                self.assertEqual("Yandex Music", detect_platform(url))
        self.assertEqual("Web", detect_platform("https://music.yandex.uz.example.org/"))

    def test_format_normalization_and_selector(self):
        metadata = normalize_yt_dlp_metadata(
            {
                "title": "Example",
                "duration": 65,
                "formats": [
                    {"height": 360, "vcodec": "avc1", "acodec": "none"},
                    {"height": 720, "vcodec": "avc1", "acodec": "none"},
                    {"vcodec": "none", "acodec": "mp4a"},
                ],
            },
            "https://youtube.com/watch?v=1",
            "YouTube",
        )
        self.assertEqual(
            ["best", "720", "360", "audio"],
            [item.key for item in metadata.available_formats],
        )
        self.assertIn("height<=480", format_selector("480"))

    def test_compact_callback_round_trip(self):
        encoded = CallbackCodec.encode("Abc12345", "1080")
        self.assertLessEqual(len(encoded.encode()), 64)
        self.assertEqual(("Abc12345", "1080"), CallbackCodec.decode(encoded))
        with self.assertRaises(ValueError):
            CallbackCodec.decode("dl:bad:root")

    def test_cookie_selection_and_safe_inspection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cookie = root / "instagram.txt"
            cookie.write_text(
                "# Netscape HTTP Cookie File\n.instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tsecret\n"
            )
            self.assertEqual(cookie, cookie_file_for("Instagram", root))
            ok, message = CookieStore(root).validate_for("instagram")
            self.assertTrue(ok)
            self.assertNotIn("secret", message)

    def test_file_detection_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "job123"
            job.mkdir()
            media = job / "movie.mp4"
            media.write_bytes(b"video")
            (job / "ignored.json").write_text("{}")
            self.assertEqual([media.resolve()], find_downloaded_paths(job))
            cleanup_job_directory(job, root)
            self.assertFalse(job.exists())
            with self.assertRaises(ValueError):
                cleanup_job_directory(root, root)

    def test_omniget_ndjson_parser(self):
        values = parse_omniget_json(
            'noise\n{"type":"progress","percent":50}\n{"file_path":"x.mp4"}'
        )
        self.assertEqual("progress", values[0]["type"])
        self.assertEqual("x.mp4", values[1]["file_path"])

    def test_fallback_policy(self):
        class Fallback:
            available = True

        service = DownloadService(object(), Fallback(), Path("/tmp/download-test"))
        self.assertTrue(service.should_fallback(Exception("network"), "Instagram"))
        self.assertFalse(service.should_fallback(Exception("network"), "YouTube"))


class DownloadSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runtime = DownloaderRuntime(
            replace(DownloaderSettings.from_env(), database_path=directory / "jobs.db")
        )
        await self.runtime.registry.initialize()
        self.client = SimpleNamespace(
            get_me=AsyncMock(return_value=SimpleNamespace(id=101)),
            edit_message_text=AsyncMock(),
        )
        self.runtime.clients[101] = self.client
        self.message = SimpleNamespace(
            command=["dl"], chat=SimpleNamespace(id=102), id=103, reply_to_message=None
        )

    async def test_plain_yandex_music_command_queues_audio_without_control(self):
        self.message.text = (
            ".dl https://music.yandex.uz/album/123/track/456"
            "?utm_source=web&utm_medium=copy_link"
        )
        self.runtime._execute = AsyncMock()
        url, choice = parse_download_request(self.message)
        self.assertIsNone(choice)
        job = await self.runtime.submit(self.client, self.message, url, choice)
        self.assertIsNotNone(job)
        await asyncio.gather(*self.runtime.tasks)
        self.runtime._execute.assert_awaited_once_with(job)
        stored = await self.runtime.registry.get(job.id)
        self.assertEqual(
            (stored.platform, stored.selected_format), ("Yandex Music", "audio")
        )

    async def test_missing_companion_chat_marks_interactive_job_failed(self):
        url = "https://youtu.be/example"
        send_job = AsyncMock(
            side_effect=TelegramBadRequest(
                method=SendMessage(chat_id=1, text="example"),
                message="Bad Request: chat not found",
            )
        )
        self.runtime.control = SimpleNamespace(send_job=send_job)
        self.runtime.service.analyze = AsyncMock(
            return_value=MediaMetadata(
                url=url,
                platform="YouTube",
                title="Example",
                available_formats=(FormatChoice("720", "720p"),),
            )
        )

        result = await self.runtime.submit(self.client, self.message, url)

        self.assertIsNone(result)
        job = send_job.await_args.args[0]
        stored = await self.runtime.registry.get(job.id)
        self.assertEqual(stored.status, JobStatus.FAILED)
        self.assertIn("/start", self.client.edit_message_text.await_args.args[2])


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = JobRegistry(Path(self.temporary.name) / "jobs.db")
        await self.registry.initialize()

    async def asyncTearDown(self):
        self.temporary.cleanup()

    def job(self, *, expires_delta=timedelta(minutes=20)):
        now = datetime.now(timezone.utc)
        return DownloadJob(
            id="Abc12345",
            url="https://example.com/media",
            source_account_id=1,
            source_chat_id=2,
            source_message_id=3,
            reply_to_message_id=None,
            platform="Web",
            status=JobStatus.PENDING,
            created_at=now,
            expires_at=now + expires_delta,
        )

    async def test_lifecycle_and_duplicate_callback_protection(self):
        await self.registry.create(self.job())
        formats = (FormatChoice("best", "Original"), FormatChoice("480", "480p", 480))
        await self.registry.set_metadata(
            "Abc12345",
            title="Video",
            platform="Web",
            formats=formats,
            metadata={"x": 1},
        )
        claimed = await self.registry.claim("Abc12345", "480")
        duplicate = await self.registry.claim("Abc12345", "480")
        self.assertEqual(JobStatus.PENDING, claimed.status)
        self.assertEqual("480", claimed.selected_format)
        self.assertIsNone(duplicate)

    async def test_expiration(self):
        await self.registry.create(self.job(expires_delta=timedelta(seconds=-1)))
        formats = (FormatChoice("best", "Original"),)
        await self.registry.set_metadata(
            "Abc12345", title="Video", platform="Web", formats=formats, metadata={}
        )
        self.assertIsNone(await self.registry.claim("Abc12345", "best"))
        self.assertEqual(
            JobStatus.EXPIRED, (await self.registry.get("Abc12345")).status
        )


if __name__ == "__main__":
    unittest.main()
