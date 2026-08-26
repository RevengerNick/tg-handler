PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS peers (
    peer_id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    username TEXT,
    display_name TEXT NOT NULL,
    is_bot INTEGER NOT NULL DEFAULT 0,
    is_contact INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    peer_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    edit_date TEXT,
    direction TEXT NOT NULL CHECK(direction IN ('incoming', 'outgoing')),
    text TEXT NOT NULL DEFAULT '',
    media_type TEXT,
    media_name TEXT,
    telegram_unread INTEGER NOT NULL DEFAULT 0,
    surfaced_at TEXT,
    deleted_at TEXT,
    raw_hash TEXT NOT NULL,
    PRIMARY KEY (peer_id, message_id),
    FOREIGN KEY (peer_id) REFERENCES peers(peer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dialog_state (
    peer_id INTEGER PRIMARY KEY,
    read_inbox_max_id INTEGER NOT NULL DEFAULT 0,
    unread_count INTEGER NOT NULL DEFAULT 0,
    last_message_id INTEGER NOT NULL DEFAULT 0,
    refreshed_at TEXT NOT NULL,
    FOREIGN KEY (peer_id) REFERENCES peers(peer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS surface_batches (
    batch_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reserved', 'delivered', 'expired'))
);

CREATE TABLE IF NOT EXISTS surface_batch_messages (
    batch_id TEXT NOT NULL,
    peer_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (batch_id, peer_id, message_id),
    FOREIGN KEY (batch_id) REFERENCES surface_batches(batch_id) ON DELETE CASCADE,
    FOREIGN KEY (peer_id, message_id) REFERENCES messages(peer_id, message_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS search_cache (
    scope TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    result TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (scope, query_hash)
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    peer_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (peer_id, message_id, content_hash, model)
);

CREATE TABLE IF NOT EXISTS mark_read_confirmations (
    token_hash TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    peer_id INTEGER NOT NULL,
    max_message_id INTEGER NOT NULL,
    message_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    confirmed_at TEXT,
    FOREIGN KEY (peer_id) REFERENCES peers(peer_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_unread
    ON messages(telegram_unread, surfaced_at, deleted_at, date DESC);
CREATE INDEX IF NOT EXISTS idx_messages_peer_date
    ON messages(peer_id, date DESC, message_id DESC);
CREATE INDEX IF NOT EXISTS idx_peers_name ON peers(display_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON surface_batches(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_confirmations_expiry ON mark_read_confirmations(expires_at);

CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    peer_id UNINDEXED,
    message_id UNINDEXED,
    text,
    display_name,
    username,
    tokenize='unicode61 remove_diacritics 2'
);
