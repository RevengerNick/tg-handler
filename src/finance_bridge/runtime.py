"""Reuse the selected authenticated client; never send messages or mark the bank chat read."""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
import logging

import aiohttp

from .config import BridgeSettings, HUMO_PEER_ID
from .outbox import Outbox

log = logging.getLogger(__name__)
ACK_STATUSES = {'created', 'matched', 'duplicate', 'unrecognized', 'needs_account', 'before_opening'}


def notification(message, owner_id):
    """Recheck canonical identities even after the Pyrogram filter has accepted a message."""
    chat, sender = getattr(message, 'chat', None), getattr(message, 'from_user', None)
    if (getattr(chat, 'id', None) != HUMO_PEER_ID or getattr(sender, 'id', None) != HUMO_PEER_ID
            or getattr(message, 'outgoing', False) or getattr(message, 'service', None)
            or getattr(message, 'forward_date', None)):
        return None
    body, when = getattr(message, 'text', None), getattr(message, 'date', None)
    if not body or not when:
        return None
    # All text receipts (including unknown future formats) reach the collector's debug inbox.
    if len(body) > 2048:
        raise ValueError('Bank text exceeds collector limit')
    when = when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)
    return {'device_id': f'tg-humo-{owner_id}', 'event_id': f'{HUMO_PEER_ID}:{int(message.id)}',
            'bank': 'humo', 'app_package': f'telegram:{HUMO_PEER_ID}',
            'title': 'HUMO Card', 'text': body, 'event_time': when.isoformat()}


class FinanceBridge:
    def __init__(self, settings):
        self.settings = settings
        self.client = None
        self.outbox = None
        self.tasks = []
        self.wake = asyncio.Event()

    async def register_client(self, client, self_id=None):
        if not self.settings.enabled:
            return
        self.settings.validate()
        identity = self_id or int((await client.get_me()).id)
        if identity != self.settings.owner_id:
            return
        if self.client is not None and self.client is not client:
            return
        self.client = client
        if self.outbox is None:
            self.outbox = await asyncio.to_thread(Outbox, self.settings.database)
        if not getattr(client, '_finance_humo_installed', False):
            from pyrogram import filters
            from pyrogram.handlers import MessageHandler

            async def on_message(_client, message):
                try:
                    await self.ingest(message)
                except Exception as exc:
                    log.warning('Finance bridge enqueue failed (%s); catch-up will retry', type(exc).__name__)

            client.add_handler(MessageHandler(on_message,
                filters.chat(HUMO_PEER_ID) & filters.user(HUMO_PEER_ID) & filters.incoming & filters.private), group=90)
            client._finance_humo_installed = True
        if not self.tasks:
            self.tasks = [asyncio.create_task(self._delivery_loop()), asyncio.create_task(self._history_loop())]
            log.warning('Finance HUMO bridge started (one selected account, one bank peer)')
        self.wake.set()

    async def ingest(self, message):
        payload = notification(message, self.settings.owner_id)
        if payload:
            await asyncio.to_thread(self.outbox.enqueue, payload)

    async def catch_up(self):
        cursor = await asyncio.to_thread(self.outbox.get_cursor)
        cutoff = datetime.now(timezone.utc) - timedelta(days=30 if cursor else self.settings.backfill_days)
        newest = cursor
        complete = False
        # Financial bots have low traffic; cap one pass without silently advancing past a gap.
        async for index, message in self._history():
            when = message.date
            when = when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)
            if int(message.id) <= cursor or when < cutoff:
                complete = True
                break
            await self.ingest(message)
            newest = max(newest, int(message.id))
        else:
            complete = True
        if not complete:
            raise RuntimeError('Finance history scan reached its bounded limit; cursor preserved')
        await asyncio.to_thread(self.outbox.set_cursor, newest)
        await asyncio.to_thread(self.outbox.redact_rejected)

    async def _history(self):
        index = 0
        async for message in self.client.get_chat_history(HUMO_PEER_ID, limit=10001):
            index += 1
            if index > 10000:
                # Yield a sentinel through an exception so the cursor is never advanced on truncation.
                raise RuntimeError('Finance history limit reached')
            yield index, message

    async def _history_loop(self):
        while True:
            self.wake.clear()
            delay = 60
            try:
                await self.catch_up()
            except Exception as exc:
                delay = max(60, min(3600, int(getattr(exc, 'value', 60))))
                log.warning('Finance history catch-up failed (%s); cursor preserved', type(exc).__name__)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=delay)

    async def deliver_one(self, http):
        row = await asyncio.to_thread(self.outbox.due)
        if row is None:
            return False
        try:
            async with http.post(self.settings.url, json=json.loads(row['payload']),
                                 headers={'X-Collector-Token': self.settings.token}, allow_redirects=False) as response:
                # Do not log URLs, headers, financial content or response bodies.
                if response.status == 200:
                    body = await response.json()
                    state = body.get('status')
                    if state not in ACK_STATUSES:
                        raise ValueError('Unknown collector acknowledgement')
                    await asyncio.to_thread(self.outbox.finish, row['event_id'], state)
                else:
                    await asyncio.to_thread(self.outbox.fail, row['event_id'], row['attempts'] + 1,
                                            f'HTTP {response.status}', permanent=response.status in {400, 413, 422})
        except Exception as exc:
            await asyncio.to_thread(self.outbox.fail, row['event_id'], row['attempts'] + 1, type(exc).__name__)
        return True

    async def _delivery_loop(self):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), trust_env=False) as http:
            while True:
                try:
                    found = await self.deliver_one(http)
                except Exception as exc:
                    log.warning('Finance outbox worker failed (%s); queued data retained', type(exc).__name__)
                    found = False
                await asyncio.sleep(0.1 if found else 2)

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.tasks = []


def get_runtime():
    return FinanceBridge(BridgeSettings.from_env())
