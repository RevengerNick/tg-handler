import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.telegram_reader.api.app import attach_reader_api
from src.telegram_reader.config.settings import ReaderSettings


class FakeRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.unread = SimpleNamespace()
        self.search = SimpleNamespace()
        self.mark_read = SimpleNamespace()

    def status(self):
        return {"ready": True, "telegram_connected": True}


def settings(**changes):
    base = ReaderSettings(
        enabled=True, database_path="unused", api_token="app-token",
        require_cf_access=True, cf_client_id="cf-id", cf_client_secret="cf-secret",
        body_limit_bytes=1024, rate_limit_per_minute=20,
        reservation_ttl_seconds=180, confirmation_ttl_seconds=300,
        max_unread_messages=500, max_search_candidates=150,
        reconcile_min_interval_seconds=60, max_dialogs_per_reconcile=500,
        timezone="Asia/Tashkent",
    )
    return replace(base, **changes)


def headers(**changes):
    result = {
        "Authorization": "Bearer app-token",
        "CF-Access-Client-Id": "cf-id",
        "CF-Access-Client-Secret": "cf-secret",
    }
    result.update(changes)
    return result


class ApiSecurityTest(unittest.TestCase):
    def app(self, custom_settings=None):
        app = FastAPI()
        attach_reader_api(app, FakeRuntime(custom_settings or settings()))
        return app

    def test_both_authentication_layers_are_required(self):
        with TestClient(self.app()) as client:
            self.assertEqual(401, client.get("/v1/status").status_code)
            self.assertEqual(401, client.get("/v1/status", headers={"Authorization": "Bearer app-token"}).status_code)
            self.assertEqual(401, client.get("/v1/status", headers=headers(Authorization="Bearer wrong")).status_code)
            response = client.get("/v1/status", headers=headers())
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.headers.get("X-Request-Id"))

    def test_rate_limit_and_body_limit(self):
        with TestClient(self.app(settings(rate_limit_per_minute=2))) as client:
            self.assertEqual(200, client.get("/v1/status", headers=headers()).status_code)
            self.assertEqual(200, client.get("/v1/status", headers=headers()).status_code)
            self.assertEqual(429, client.get("/v1/status", headers=headers()).status_code)
        with TestClient(self.app()) as client:
            response = client.post(
                "/v1/telegram/search/private", headers=headers(**{"Content-Length": "2048"}),
                content=b"{}",
            )
            self.assertEqual(413, response.status_code)


if __name__ == "__main__":
    unittest.main()
