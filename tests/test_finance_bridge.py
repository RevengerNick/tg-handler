import json
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from src.finance_bridge.config import BridgeSettings, HUMO_PEER_ID
from src.finance_bridge.outbox import Outbox
from src.finance_bridge.runtime import FinanceBridge, notification


def message(message_id=1, **overrides):
    values = dict(id=message_id, chat=SimpleNamespace(id=HUMO_PEER_ID),
                  from_user=SimpleNamespace(id=HUMO_PEER_ID), date=datetime.now(timezone.utc),
                  text='Synthetic bank text', outgoing=False, service=None, forward_date=None)
    return SimpleNamespace(**(values | overrides))


class Response:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error = status, body or {'status': 'created'}, error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.body


class HTTP:
    def __init__(self, response):
        self.response, self.calls = response, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'outbox.sqlite3'
        self.settings = BridgeSettings(enabled=True, owner_id=42,
            url='http://collector:8080/v1/notifications', token='x' * 32, database=self.path)
        self.bridge = FinanceBridge(self.settings)
        self.bridge.outbox = Outbox(self.path)

    def test_canonical_sender_filters_and_stable_event_identity(self):
        payload = notification(message(), 42)
        self.assertEqual(payload['event_id'], f'{HUMO_PEER_ID}:1')
        self.assertEqual(payload['app_package'], f'telegram:{HUMO_PEER_ID}')
        for patch in ({'chat': SimpleNamespace(id=1)}, {'from_user': SimpleNamespace(id=1)},
                      {'outgoing': True}, {'service': True}, {'forward_date': datetime.now()},
                      {'text': ''}):
            self.assertIsNone(notification(message(**patch), 42))

    async def test_durable_retry_then_acknowledgement_redacts_body(self):
        await self.bridge.ingest(message())
        await self.bridge.ingest(message())
        self.assertEqual(Outbox(self.path).stats(), {'pending': 1})
        await self.bridge.deliver_one(HTTP(Response(error=TimeoutError())))
        with self.bridge.outbox.connect() as db:
            row = db.execute('SELECT * FROM deliveries').fetchone()
            self.assertEqual(row['attempts'], 1)
            self.assertIn('Synthetic bank text', row['payload'])
            db.execute('UPDATE deliveries SET next_attempt=0')
        restarted = FinanceBridge(self.settings)
        restarted.outbox = Outbox(self.path)
        http = HTTP(Response(body={'status': 'duplicate'}))
        await restarted.deliver_one(http)
        self.assertEqual(restarted.outbox.stats(), {'delivered': 1})
        self.assertFalse(http.calls[0][1]['allow_redirects'])
        with restarted.outbox.connect() as db:
            self.assertIsNone(db.execute('SELECT payload FROM deliveries').fetchone()[0])

    async def test_rejections_and_unknown_acknowledgements_remain_visible(self):
        for response, expected in [(Response(status=401), 'pending'),
                                   (Response(status=422), 'rejected'),
                                   (Response(body={'status': 'surprise'}), 'pending')]:
            with self.bridge.outbox.connect() as db:
                db.execute('DELETE FROM deliveries')
            await self.bridge.ingest(message())
            await self.bridge.deliver_one(HTTP(response))
            self.assertEqual(self.bridge.outbox.stats(), {expected: 1})

    async def test_history_cursor_does_not_skip_live_or_interrupted_messages(self):
        live = message(30)
        await self.bridge.ingest(live)
        self.assertEqual(self.bridge.outbox.get_cursor(), 0)

        async def interrupted(*args, **kwargs):
            yield message(20)
            raise ConnectionError('simulated network outage')
        self.bridge.client = SimpleNamespace(get_chat_history=interrupted)
        with self.assertRaises(ConnectionError):
            await self.bridge.catch_up()
        self.assertEqual(self.bridge.outbox.get_cursor(), 0)

        async def complete(*args, **kwargs):
            self.assertEqual(args[0], HUMO_PEER_ID)
            yield live
            yield message(20)
            yield message(10)
            yield message(5, date=datetime.now(timezone.utc) - timedelta(days=4))
        self.bridge.client.get_chat_history = complete
        await self.bridge.catch_up()
        self.assertEqual(self.bridge.outbox.get_cursor(), 30)
        self.assertEqual(self.bridge.outbox.stats(), {'pending': 3})
        await self.bridge.catch_up()
        self.assertEqual(self.bridge.outbox.stats(), {'pending': 3})

    async def test_wrong_telegram_account_never_attaches_handlers(self):
        await self.bridge.register_client(SimpleNamespace(), self_id=999)
        self.assertIsNone(self.bridge.client)
        self.assertEqual(self.bridge.tasks, [])

    def test_configuration_does_not_expose_token_or_accept_redirect_endpoint(self):
        self.settings.validate()
        self.assertNotIn('x' * 32, repr(self.settings))
        for url in ['ftp://host/v1/notifications', 'http://user:pass@host/v1/notifications',
                    'https://host/redirect?token=test']:
            with self.assertRaises(ValueError):
                BridgeSettings(enabled=True, owner_id=42, token='x' * 32, url=url).validate()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
