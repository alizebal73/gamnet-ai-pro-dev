-- P3-4: reservations + customer queue + group sessions.
-- Reservations conflict-detect on (pc, time); the queue is FIFO with
-- optional VIP boost; groups link sessions that end together.

CREATE TABLE IF NOT EXISTS reservations (
    id            TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    pc_id         TEXT NOT NULL REFERENCES pcs(id),
    starts_at     TEXT NOT NULL,
    ends_at       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'BOOKED'
                  CHECK (status IN ('BOOKED', 'SEATED', 'CANCELLED',
                                    'EXPIRED', 'NO_SHOW')),
    note          TEXT,
    cancel_reason TEXT,
    created_by    TEXT NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK (ends_at > starts_at)
);
CREATE INDEX IF NOT EXISTS idx_reservations_pc_time
    ON reservations(pc_id, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_reservations_customer
    ON reservations(customer_id);

CREATE TABLE IF NOT EXISTS queue_entries (
    id         TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    pc_id      TEXT REFERENCES pcs(id),
    priority   INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'WAITING'
               CHECK (status IN ('WAITING', 'CALLED', 'SEATED',
                                 'CANCELLED', 'EXPIRED')),
    note       TEXT,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    called_at  TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_status_time
    ON queue_entries(status, created_at);

CREATE TABLE IF NOT EXISTS session_groups (
    id             TEXT PRIMARY KEY,
    name           TEXT,
    shared_ends_at TEXT,
    status         TEXT NOT NULL DEFAULT 'OPEN'
                   CHECK (status IN ('OPEN', 'CLOSED')),
    created_by     TEXT NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL,
    closed_at      TEXT
);
ALTER TABLE sessions ADD COLUMN group_id TEXT REFERENCES session_groups(id);
CREATE INDEX IF NOT EXISTS idx_sessions_group ON sessions(group_id);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('queue_vip_priority', '0', '2026-01-01T00:00:00'),
    ('queue_expire_min', '60', '2026-01-01T00:00:00');
