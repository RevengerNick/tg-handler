import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.services import ai_core


class FakeResponse:
    text = "OK"
    candidates = ()


async def chunks():
    yield FakeResponse()


class FakeChat:
    async def send_message(self, contents):
        return FakeResponse()

    async def send_message_stream(self, contents):
        return chunks()


class FakeChats:
    def __init__(self):
        self.create_calls = 0

    def create(self, **kwargs):
        self.create_calls += 1
        return FakeChat()


class FakeModels:
    async def generate_content(self, **kwargs):
        return FakeResponse()

    async def generate_content_stream(self, **kwargs):
        return chunks()


class AiCoreAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ai_core.ASYNC_CHAT_SESSIONS.clear()
        ai_core.current_key_index = 0
        self.chats = FakeChats()
        self.client = SimpleNamespace(
            aio=SimpleNamespace(chats=self.chats, models=FakeModels())
        )

    def patches(self):
        return (
            patch.object(ai_core, "GEMINI_KEYS", ["test-key"]),
            patch.object(ai_core, "get_ai_client", return_value=self.client),
        )

    async def test_ai_stream_awaits_async_model_method(self):
        keys_patch, client_patch = self.patches()
        with keys_patch, client_patch:
            stream = await ai_core.get_gemini_stream(None, "hello", is_chat=False)
            self.assertEqual(["OK"], [chunk.text async for chunk in stream])

    async def test_ait_awaits_async_model_method(self):
        keys_patch, client_patch = self.patches()
        with keys_patch, client_patch:
            result = await ai_core.ask_gemini_oneshot("hello")

        self.assertEqual("OK", result)

    async def test_chat_creates_async_chat_synchronously_then_awaits_stream(self):
        keys_patch, client_patch = self.patches()
        with keys_patch, client_patch:
            stream = await ai_core.get_gemini_stream(101, "hello", is_chat=True)
            self.assertEqual(["OK"], [chunk.text async for chunk in stream])
            self.assertEqual(1, self.chats.create_calls)

    async def test_chatt_creates_async_chat_synchronously_then_awaits_message(self):
        keys_patch, client_patch = self.patches()
        with keys_patch, client_patch:
            result = await ai_core.ask_gemini_chat(202, "hello")

        self.assertEqual(1, self.chats.create_calls)
        self.assertEqual("OK", result)

    async def test_programming_error_is_not_masked_as_exhausted_keys(self):
        async def broken_request():
            raise TypeError("bad await")

        with (
            patch.object(ai_core, "GEMINI_KEYS", ["one", "two", "three"]),
            self.assertRaisesRegex(TypeError, "bad await"),
        ):
            await ai_core.rotate_key_and_retry(broken_request)

    def test_model_without_search_does_not_enable_empty_tool_config(self):
        with patch.dict(ai_core.SETTINGS, {"model_key": "1"}, clear=False):
            _, config = ai_core.get_ai_config()

        self.assertIsNone(config.tools)
        self.assertTrue(config.automatic_function_calling.disable)


if __name__ == "__main__":
    unittest.main()
