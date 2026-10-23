"""Small durable outbox. Each call owns a connection and can run in a worker thread."""
import json
from contextlib import contextmanager
import os
import sqlite3
import time


class Outbox:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS deliveries (
                    event_id TEXT PRIMARY KEY, payload TEXT, state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                    result TEXT, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, payload):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO deliveries(event_id,payload,created_at) VALUES(?,?,?)',
                       (payload['event_id'], json.dumps(payload, ensure_ascii=False), time.time()))

    def due(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM deliveries WHERE state='pending' AND next_attempt<=? ORDER BY created_at,event_id LIMIT 1",
                             (time.time(),)).fetchone()
            return dict(row) if row else None

    def finish(self, event_id, result):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET state='delivered',result=?,payload=NULL WHERE event_id=?",
                       (result, event_id))

    def fail(self, event_id, attempts, reason, *, permanent=False):
        with self.connect() as db:
            db.execute('UPDATE deliveries SET attempts=?,next_attempt=?,result=?,state=? WHERE event_id=?',
                       (attempts, time.time() + min(300, 5 * 2 ** min(attempts, 6)), reason,
                        'rejected' if permanent else 'pending', event_id))

    def get_cursor(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='cursor'").fetchone()
            return int(row[0]) if row else 0

    def set_cursor(self, cursor):
        with self.connect() as db:
            db.execute("INSERT INTO metadata VALUES('cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (str(cursor),))

    def redact_rejected(self):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET payload=NULL WHERE state='rejected' AND created_at<?",
                       (time.time() - 30 * 86400,))

    def stats(self):
        with self.connect() as db:
            return dict(db.execute('SELECT state, count(*) FROM deliveries GROUP BY state').fetchall())
