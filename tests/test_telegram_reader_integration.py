import ast
import asyncio
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram.errors import FloodWait

from src.telegram_reader.config.settings import ReaderSettings
from src.telegram_reader.runtime import ReaderRuntime
from src.telegram_reader.services import MarkReadService, SearchService, UnreadService
from src.telegram_reader.storage import Database
from src.telegram_reader.storage.repositories import ReaderRepository
from src.telegram_reader.telegram.client import ClientRegistry


def chat(peer_id, kind="private", name="Александр", username="alex", bot=False):
    return SimpleNamespace(
        id=peer_id, type=kind, first_name=name if kind == "private" else None,
        last_name="", title=name if kind != "private" else None,
        username=username, is_bot=bot, is_contact=True,
    )


def message(peer, mid, text, outgoing=False, sender_bot=False, link=None):
    return SimpleNamespace(
        id=mid, chat=peer, from_user=SimpleNamespace(is_bot=sender_bot),
        outgoing=outgoing, service=None, text=text, caption=None,
        date=datetime(2026, 8, 26, 10, mid, tzinfo=timezone.utc), edit_date=None,
        photo=None, voice=None, video=None, document=None, audio=None,
        animation=None, sticker=None, link=link, empty=False,
    )


class FakeClient:
    def __init__(self):
        self.me = SimpleNamespace(id=999)
        self.get_me_calls = 0
        self.person = chat(10)
        self.bot = chat(20, bot=True, name="Bot")
        self.channel = chat(-1001, kind="channel", name="AI News", username="ainews")
        self.dialogs = [
            SimpleNamespace(chat=self.person, folder_id=0, unread_messages_count=2),
            SimpleNamespace(chat=self.bot, folder_id=0, unread_messages_count=0),
            SimpleNamespace(chat=self.channel, folder_id=0, unread_messages_count=0),
        ]
        self.histories = {10: [message(self.person, 2, "Второе сообщение"), message(self.person, 1, "Первое сообщение")]}
        self.global_results = []
        self.read_calls = []
        self.handlers = []

    async def get_me(self):
        self.get_me_calls += 1
        return self.me

    async def get_dialogs(self, limit=0):
        for item in self.dialogs[:limit or None]:
            yield item

    async def get_chat_history(self, peer_id, limit=0, **_kwargs):
        for item in self.histories.get(peer_id, [])[:limit or None]:
            yield item

    async def search_global(self, query="", limit=0, **_kwargs):
        for item in self.global_results[:limit or None]:
            yield item

    async def search_messages(self, peer_id, query="", limit=0, **_kwargs):
        for item in self.histories.get(peer_id, [])[:limit or None]:
            if query.casefold() in (item.text or "").casefold():
                yield item

    async def get_messages(self, peer_id, message_ids=None, **_kwargs):
        wanted = set(message_ids or [])
        return [item for item in self.histories.get(peer_id, []) if item.id in wanted]

    async def read_chat_history(self, peer_id, max_id=0):
        self.read_calls.append((peer_id, max_id))
        return True

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))


def settings(database_path):
    return ReaderSettings(
        enabled=True, database_path=database_path, api_token="token",
        require_cf_access=False, cf_client_id="", cf_client_secret="",
        body_limit_bytes=262144, rate_limit_per_minute=60,
        reservation_ttl_seconds=180, confirmation_ttl_seconds=300,
        max_unread_messages=500, max_search_candidates=150,
        reconcile_min_interval_seconds=0, max_dialogs_per_reconcile=500,
        timezone="Asia/Tashkent",
    )


class ReaderIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = str(Path(self.tmp.name) / "reader.sqlite")
        self.db = Database(db_path)
        self.db.migrate()
        self.repo = ReaderRepository(self.db)
        self.registry = ClientRegistry()
        self.client = FakeClient()
        await self.registry.add(self.client, self_id=self.client.me.id)
        self.settings = settings(db_path)
        self.unread = UnreadService(self.registry, self.repo, self.settings)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_real_unread_surface_lifecycle_and_official_read_reconciliation(self):
        boundary = {10: {"read_inbox_max_id": 0, "unread_count": 2, "last_message_id": 2}}
        with patch("src.telegram_reader.services.unread_service.fetch_read_boundaries", new=AsyncMock(return_value=boundary)):
            first = await self.unread.unread("owner", "new_only", None, 10, 10)
            self.assertEqual(2, first["message_count"])
            await self.unread.commit("owner", first["batch_id"])
            repeated = await self.unread.unread("owner", "new_only", None, 10, 10)
            self.assertEqual(0, repeated["message_count"])
            all_unread = await self.unread.unread("owner", "all_unread", None, 10, 10)
            self.assertEqual(2, all_unread["message_count"])

        read_boundary = {10: {"read_inbox_max_id": 2, "unread_count": 0, "last_message_id": 2}}
        with patch("src.telegram_reader.services.unread_service.fetch_read_boundaries", new=AsyncMock(return_value=read_boundary)):
            after_official_read = await self.unread.unread("owner", "all_unread", None, 10, 10)
        self.assertEqual(0, after_official_read["message_count"])
        with self.db.connection() as connection:
            peer_types = {row[0] for row in connection.execute("SELECT type FROM peers")}
        self.assertEqual({"private"}, peer_types)
        self.assertEqual(0, self.client.get_me_calls)

    async def test_registry_caches_identity_and_deduplicates_registration(self):
        registry = ClientRegistry()
        client = FakeClient()
        self.assertTrue(await registry.add(client, self_id=client.me.id))
        self.assertFalse(await registry.add(client))
        self.assertEqual(999, await registry.self_id())
        self.assertEqual(0, client.get_me_calls)

    async def test_reconcile_reuses_recent_success_instead_of_retrying_telegram(self):
        throttled = UnreadService(
            self.registry,
            self.repo,
            replace(self.settings, reconcile_min_interval_seconds=60),
        )
        boundary = {10: {"read_inbox_max_id": 0, "unread_count": 2, "last_message_id": 2}}
        fetch = AsyncMock(return_value=boundary)
        with patch("src.telegram_reader.services.unread_service.fetch_read_boundaries", new=fetch):
            first = await throttled.reconcile()
            second = await throttled.reconcile()

        self.assertTrue(first["performed"])
        self.assertTrue(second["refreshed"])
        self.assertFalse(second["performed"])
        self.assertEqual("recent", second["reason"])
        self.assertEqual(1, fetch.await_count)

    async def test_floodwait_becomes_one_cooldown_instead_of_retries_or_error(self):
        throttled = UnreadService(
            self.registry,
            self.repo,
            replace(self.settings, reconcile_min_interval_seconds=60),
        )
        fetch = AsyncMock(side_effect=FloodWait(18))
        with patch("src.telegram_reader.services.unread_service.fetch_read_boundaries", new=fetch):
            first = await throttled.reconcile()
            second = await throttled.reconcile()

        self.assertFalse(first["refreshed"])
        self.assertEqual("flood_wait", first["reason"])
        self.assertGreaterEqual(first["retry_after_seconds"], 60)
        self.assertFalse(second["performed"])
        self.assertEqual("flood_wait", second["reason"])
        self.assertEqual(1, fetch.await_count)

    async def test_reader_uses_only_first_account(self):
        runtime = SimpleNamespace(
            registry=ClientRegistry(),
            unread=SimpleNamespace(reconcile=AsyncMock(return_value={"refreshed": True})),
        )
        first, second = FakeClient(), FakeClient()
        install = AsyncMock()
        with patch("src.telegram_reader.runtime.install_handlers", new=install):
            await ReaderRuntime.register_client(runtime, first, self_id=999)
            await ReaderRuntime.register_client(runtime, second, self_id=888)

        self.assertEqual(1, runtime.registry.count)
        self.assertIs(first, runtime.registry.primary())
        self.assertEqual(1, install.await_count)
        self.assertEqual(1, runtime.unread.reconcile.await_count)

    async def test_prepare_is_read_only_and_confirm_acknowledges_exact_max_id(self):
        boundary = {10: {"read_inbox_max_id": 0, "unread_count": 2, "last_message_id": 2}}
        mark_read = MarkReadService(self.registry, self.repo, self.settings, self.unread)
        with patch("src.telegram_reader.services.unread_service.fetch_read_boundaries", new=AsyncMock(return_value=boundary)):
            prepared = await mark_read.prepare("owner", "Александр", max_message_id=1)
            self.assertTrue(prepared["confirmation_required"])
            self.assertEqual([1, 2], [row["message_id"] for row in self.repo.unread_for_peer(10)])
            confirmed = await mark_read.confirm("owner", prepared["confirmation_token"])
        self.assertEqual([(10, 1)], self.client.read_calls)
        self.assertEqual(1, confirmed["messages_marked_read"])
        self.assertEqual([2], [row["message_id"] for row in self.repo.unread_for_peer(10)])

    async def test_joined_channel_search_is_explicit_and_semantic_stage_falls_back(self):
        channel_message = message(
            self.client.channel, 50, "Запуск Qwen на видеокарте с 16 ГБ VRAM",
            link="https://t.me/ainews/50",
        )
        self.client.global_results = [channel_message, message(self.client.person, 3, "Qwen лично")]
        service = SearchService(self.registry, self.repo, self.settings, self.unread)
        result = await service.search_channels(
            "Qwen 16 ГБ", "semantic", "joined_channels", [], None, None,
            20, None, True, 20, False,
        )
        self.assertEqual(1, len(result["results"]))
        self.assertEqual("AI News", result["results"][0]["channel"])
        self.assertFalse(result["semantic_available"])
        self.assertEqual("candidate_pool", result["semantic_stage"])
        with self.assertRaises(PermissionError):
            await service.search_channels(
                "Qwen", "all_terms", "public_global", [], None, None,
                20, None, False, 20, False,
            )
        with self.assertRaises(NotImplementedError):
            await service.search_channels(
                "Qwen", "all_terms", "public_global", [], None, None,
                20, None, False, 20, True,
            )

    def test_existing_sys_commands_remain_registered(self):
        admin = Path(__file__).resolve().parents[1] / "src" / "handlers" / "admin.py"
        tree = ast.parse(admin.read_text(encoding="utf-8"))
        aliases = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "command":
                continue
            if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                aliases.update(
                    item.value for item in node.args[0].elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
        self.assertTrue({"sys", "sysglobal", "syschat"}.issubset(aliases))


if __name__ == "__main__":
    unittest.main()
