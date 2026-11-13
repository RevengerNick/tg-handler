import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from pyrogram import enums, raw, types, utils
from pyrogram.errors import ChatAdminRequired, FloodWait

from src.handlers.group_mentions import build_mention_messages, tag_all_handler


class GroupMentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_formats_usernames_and_real_name_mentions(self):
        users = [
            types.User(id=1, username="nick"),
            types.User(id=2, first_name="🚀 Аня"),
            types.User(id=3, first_name="Маша"),
        ]
        [(text, entities)] = build_mention_messages(
            users, "Ребят, просмотрите, важно -"
        )
        self.assertEqual(text, "@nick, 🚀 Аня, Маша - Ребят, просмотрите, важно -")
        client = Mock(
            resolve_peer=AsyncMock(
                side_effect=lambda uid: raw.types.InputUser(
                    user_id=uid,
                    access_hash=1,
                )
            )
        )
        parsed = await utils.parse_text_entities(
            client, text, enums.ParseMode.DISABLED, entities
        )
        wire = parsed["entities"]
        self.assertEqual([(e.offset, e.length) for e in wire], [(7, 6), (15, 4)])
        self.assertEqual([e.user_id.user_id for e in wire], [2, 3])
        for entity in wire:
            self.assertIsInstance(entity, raw.types.InputMessageEntityMentionName)
            entity.write()

    async def test_long_list_and_note_keep_telegram_limits(self):
        users = [types.User(id=i, first_name="А" * 60) for i in range(1, 205)]
        note = "важно " * 600
        messages = list(build_mention_messages(users, note))
        self.assertGreater(len(messages), 1)
        self.assertTrue(
            all(
                len(text) <= 4096 and len(entities) <= 100
                for text, entities in messages
            )
        )
        self.assertEqual(sum(len(entities) for _, entities in messages), len(users))
        self.assertTrue(messages[-1][0].endswith(" - " + note))
        self.assertEqual(
            [entities[0].offset for _, entities in messages], [0] * len(messages)
        )

    async def test_handler_preserves_topic_and_skips_duplicate_bot_and_deleted_users(
        self,
    ):
        async def members(chat_id):
            self.assertEqual(chat_id, -100123)
            for user in (
                types.User(id=1, username="nick"),
                types.User(id=1, username="nick"),
                types.User(id=2, is_bot=True),
                types.User(id=3, is_deleted=True),
                types.User(id=4, first_name="Аня"),
            ):
                yield types.ChatMember(user=user, status=enums.ChatMemberStatus.MEMBER)

        client = Mock(get_chat_members=members, send_message=AsyncMock())
        message = self.message(".tagall Ребят, важно -", count=4)
        await tag_all_handler(client, message)

        self.assertEqual(
            client.send_message.await_args.args,
            (-100123, "@nick, Аня - Ребят, важно -"),
        )
        kwargs = client.send_message.await_args.kwargs
        self.assertEqual(kwargs["entities"][0].user.id, 4)
        self.assertEqual(kwargs["message_thread_id"], 14)
        self.assertEqual(kwargs["reply_to_message_id"], 18)
        message.delete.assert_awaited_once()

    async def test_hidden_member_list_reports_error(self):
        async def members(_):
            yield types.ChatMember(
                user=types.User(id=1, username="nick"),
                status=enums.ChatMemberStatus.MEMBER,
            )
            raise ChatAdminRequired()

        client = Mock(get_chat_members=members, send_message=AsyncMock())
        message = self.message(".tag", count=2)
        await tag_all_handler(client, message)
        client.send_message.assert_not_awaited()
        self.assertIn("права аккаунта", message.edit_text.await_args.args[0])

    async def test_partial_send_reports_flood_wait_without_retrying(self):
        async def members(_):
            for i in range(101):
                yield types.ChatMember(
                    user=types.User(id=i + 1, username=f"user_{i}"),
                    status=enums.ChatMemberStatus.MEMBER,
                )

        client = Mock(
            get_chat_members=members,
            send_message=AsyncMock(side_effect=[None, FloodWait(90)]),
        )
        message = self.message(".tag", count=101)
        await tag_all_handler(client, message)
        self.assertEqual(client.send_message.await_count, 2)
        self.assertIn("90 сек.", message.edit_text.await_args.args[0])
        self.assertIn("отправлено сообщений: 1", message.edit_text.await_args.args[0])

    @staticmethod
    def message(text, count):
        return SimpleNamespace(
            text=text,
            chat=types.Chat(
                id=-100123, type=enums.ChatType.SUPERGROUP, members_count=count
            ),
            message_thread_id=14,
            reply_to_message_id=18,
            edit_text=AsyncMock(),
            delete=AsyncMock(),
        )
