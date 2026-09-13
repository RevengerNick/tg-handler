import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.downloader.backends.omniget import parse_omniget_json
from src.downloader.callbacks import CallbackCodec
from src.downloader.cookies import CookieStore
from src.downloader.files import cleanup_job_directory, find_downloaded_paths
from src.downloader.formats import format_selector, normalize_yt_dlp_metadata
from src.downloader.models import DownloadJob, FormatChoice, JobStatus
from src.downloader.platforms import cookie_file_for, detect_platform, extract_url
from src.downloader.registry import JobRegistry
from src.downloader.service import DownloadService


class DownloaderPureTests(unittest.TestCase):
    def test_url_and_platform_detection(self):
        self.assertEqual(
            "https://youtu.be/abc", extract_url(r"go https\://youtu.be/abc.")
        )
        self.assertEqual("YouTube", detect_platform("https://m.youtube.com/watch?v=1"))
        self.assertEqual("Instagram", detect_platform("https://www.instagram.com/p/1"))
        self.assertEqual("Web", detect_platform("https://evilinstagram.com/p/1"))

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
