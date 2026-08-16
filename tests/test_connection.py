import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock, call, patch
from pathlib import Path


def load_connection_module():
    """Загружает модуль без импорта тяжёлого пакета src.services."""
    pyrogram = types.ModuleType("pyrogram")
    pyrogram.Client = type("Client", (), {})
    errors = types.ModuleType("pyrogram.errors")
    for name in (
        "AuthKeyDuplicated", "AuthKeyInvalid", "SessionRevoked",
        "UserDeactivated", "FloodWait",
    ):
        setattr(errors, name, type(name, (Exception,), {}))
    sys.modules.setdefault("pyrogram", pyrogram)
    sys.modules.setdefault("pyrogram.errors", errors)

    path = Path(__file__).resolve().parents[1] / "src" / "services" / "connection.py"
    spec = importlib.util.spec_from_file_location("connection_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


connection = load_connection_module()


class ConnectionRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_internet_keeps_retrying_until_recovery(self):
        with (
            patch(
                "connection_under_test.check_internet",
                new=AsyncMock(side_effect=[False, False, True]),
            ) as check,
            patch("connection_under_test.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            connected = await connection.wait_for_internet(
                max_wait=None, check_interval=5, max_interval=600
            )

        self.assertTrue(connected)
        self.assertEqual(3, check.await_count)
        self.assertEqual([call(5), call(10)], sleep.await_args_list)


if __name__ == "__main__":
    unittest.main()
