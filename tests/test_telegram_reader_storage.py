import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.telegram_reader.services.search_service import SearchService, lexical_score
from src.telegram_reader.storage import Database
from src.telegram_reader.storage.repositories import ReaderRepository
from src.telegram_reader.telegram.search import is_real_private_incoming


NOW = "2026-08-26T10:00:00Z"


def chat(peer_id=10, kind="private", bot=False):
    return SimpleNamespace(id=peer_id, type=kind, is_bot=bot, first_name="Александр", last_name="", username="alex")


def message(mid=1, kind="private", bot=False, outgoing=False, service=None, self_chat=False):
    peer_id = 99 if self_chat else 10
    return SimpleNamespace(
        id=mid, chat=chat(peer_id, kind, bot), from_user=SimpleNamespace(is_bot=bot),
        outgoing=outgoing, service=service,
    )


class RepositoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "reader.sqlite"))
        self.db.migrate()
        self.repo = ReaderRepository(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def add_peer(self, peer_id=10, kind="private", bot=False, name="Александр"):
        self.repo.upsert_peer({
            "peer_id": peer_id, "type": kind, "username": "alex", "display_name": name,
            "is_bot": bot, "is_contact": True, "is_archived": False,
        })

    def add_message(self, mid, text="адрес сервиса", unread=True, peer_id=10, raw_hash=None):
        self.repo.upsert_message({
            "peer_id": peer_id, "message_id": mid, "date": NOW, "edit_date": None,
            "direction": "incoming", "text": text, "media_type": None, "media_name": None,
            "media_metadata": {}, "telegram_unread": unread, "raw_hash": raw_hash or f"hash-{mid}",
        })

    def test_private_user_filter_and_exclusions(self):
        self.assertTrue(is_real_private_incoming(message(), self_id=99))
        self.assertFalse(is_real_private_incoming(message(bot=True), self_id=99))
        self.assertFalse(is_real_private_incoming(message(kind="group"), self_id=99))
        self.assertFalse(is_real_private_incoming(message(kind="channel"), self_id=99))
        self.assertFalse(is_real_private_incoming(message(outgoing=True), self_id=99))
        self.assertFalse(is_real_private_incoming(message(service="new_chat_members"), self_id=99))
        self.assertFalse(is_real_private_incoming(message(self_chat=True), self_id=99))

    def test_exact_read_boundary_controls_individual_messages(self):
        self.add_peer()
        for mid in (1, 2, 3):
            self.add_message(mid)
        self.repo.update_dialog_state(10, read_inbox_max_id=2, unread_count=1, last_message_id=3)
        self.assertEqual([3], [row["message_id"] for row in self.repo.unread_for_peer(10)])

    def test_surface_reservation_commit_and_timeout_recovery(self):
        self.add_peer()
        self.add_message(1)
        first = self.repo.reserve_unread("owner", "new_only", None, 10, 10, 180)
        self.assertEqual(1, len(first["messages"]))
        self.assertEqual(1, self.repo.commit_surface_batch(first["batch_id"], "owner"))
        self.assertEqual([], self.repo.reserve_unread("owner", "new_only", None, 10, 10, 180)["messages"])
        self.assertEqual(1, len(self.repo.reserve_unread("owner", "all_unread", None, 10, 10, 180)["messages"]))

        self.add_message(2)
        reserved = self.repo.reserve_unread("owner", "new_only", None, 10, 10, 180)
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE surface_batches SET expires_at='2000-01-01T00:00:00Z' WHERE batch_id=?",
                (reserved["batch_id"],),
            )
        recovered = self.repo.reserve_unread("owner", "new_only", None, 10, 10, 180)
        self.assertEqual([2], [row["message_id"] for row in recovered["messages"]])

    def test_edit_invalidates_embedding_and_delete_removes_search_result(self):
        self.add_peer()
        self.add_message(1, raw_hash="old")
        self.repo.cache_embedding(10, 1, "old", "model", [1.0, 0.0])
        first = self.repo.reserve_unread("owner", "new_only", None, 10, 10, 180)
        self.repo.commit_surface_batch(first["batch_id"], "owner")
        self.add_message(1, text="новый адрес", raw_hash="new")
        self.assertIsNone(self.repo.get_embedding(10, 1, "old", "model"))
        self.assertEqual(1, len(self.repo.reserve_unread("owner", "new_only", None, 10, 10, 180)["messages"]))
        self.assertEqual(1, len(self.repo.search_local("private", "новый", 10)))
        self.repo.mark_deleted(10, [1])
        self.assertEqual([], self.repo.search_local("private", "новый", 10))

    def test_exact_all_any_and_fuzzy_search_modes(self):
        text = "Александр прислал адрес сервиса на Чиланзаре"
        self.assertGreater(lexical_score("адрес сервиса", text, "exact"), 0)
        self.assertGreater(lexical_score("адрес Чиланзаре", text, "all_terms"), 0)
        self.assertGreater(lexical_score("страховка адрес", text, "any_terms"), 0)
        self.assertGreater(lexical_score("адрес сервис", text, "fuzzy"), 0)
        self.assertEqual(0, lexical_score("врач", text, "exact"))

    def test_channel_scope_and_pagination_are_deterministic(self):
        self.add_peer(peer_id=-1001, kind="channel", name="AI News")
        self.add_message(1, "Qwen для 16 ГБ VRAM", peer_id=-1001)
        self.add_message(2, "Qwen benchmark для локального запуска", peer_id=-1001)
        self.assertEqual([], self.repo.search_local("private", "Qwen", 10))
        rows = self.repo.search_local("channel", "Qwen", 10)
        self.assertEqual(2, len(rows))
        service = SearchService(None, self.repo, SimpleNamespace(), None)
        page1 = service._filter_and_page(rows, "Qwen", "exact", None, None, None, 1, None, {"q": "Qwen"})
        self.assertEqual(2, page1["total_candidates"])
        self.assertIsNotNone(page1["next_cursor"])
        page2 = service._filter_and_page(rows, "Qwen", "exact", None, None, None, 1, page1["next_cursor"], {"q": "Qwen"})
        self.assertNotEqual(page1["results"][0]["message_id"], page2["results"][0]["message_id"])

    def test_search_cache_is_short_lived_and_invalidated_by_edits(self):
        self.add_peer()
        self.add_message(1, "страховка мотоцикла", raw_hash="old")
        self.repo.put_search_cache("private", "key", {"results": [1]}, ttl_seconds=60)
        self.assertEqual({"results": [1]}, self.repo.get_search_cache("private", "key"))
        self.add_message(1, "новая страховка", raw_hash="edited")
        self.assertIsNone(self.repo.get_search_cache("private", "key"))

    def test_confirmation_expiry_and_mark_read_max_id_semantics(self):
        self.add_peer()
        for mid in (1, 2, 3):
            self.add_message(mid)
        token = self.repo.create_confirmation("owner", 10, 2, 2, 300)
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE mark_read_confirmations SET expires_at='2000-01-01T00:00:00Z'"
            )
        self.assertIsNone(self.repo.consume_confirmation(token, "owner"))
        self.assertEqual(2, self.repo.mark_read_locally(10, 2))
        self.assertEqual([3], [row["message_id"] for row in self.repo.unread_for_peer(10)])


if __name__ == "__main__":
    unittest.main()
