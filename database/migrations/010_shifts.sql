-- P3-1: operator shifts + cash drawer.
-- One OPEN shift at a time (partial unique index); sales confirmed while a
-- shift is open are attached to it; CASH payments + IN/OUT movements make
-- the expected drawer at close.

CREATE TABLE IF NOT EXISTS shifts (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'OPEN'
                  CHECK (status IN ('OPEN', 'CLOSED')),
    opened_by     TEXT NOT NULL REFERENCES users(id),
    opened_at     TEXT NOT NULL,
    closed_by     TEXT REFERENCES users(id),
    closed_at     TEXT,
    opening_float INTEGER NOT NULL DEFAULT 0 CHECK (opening_float >= 0),
    expected_cash INTEGER,
    counted_cash  INTEGER,
    variance      INTEGER,
    note          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_one_open_shift
    ON shifts((1)) WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS cash_movements (
    id         TEXT PRIMARY KEY,
    shift_id   TEXT NOT NULL REFERENCES shifts(id),
    kind       TEXT NOT NULL CHECK (kind IN ('IN', 'OUT')),
    amount     INTEGER NOT NULL CHECK (amount > 0),
    reason     TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cash_movements_shift
    ON cash_movements(shift_id);

ALTER TABLE sales ADD COLUMN shift_id TEXT REFERENCES shifts(id);
CREATE INDEX IF NOT EXISTS idx_sales_shift ON sales(shift_id);

INSERT OR IGNORE INTO permissions (name, description, created_at) VALUES
    ('shift.manage', 'Open/close shifts and count the cash drawer.',
     strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at) VALUES
    ('owner',    'shift.manage', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('manager',  'shift.manage', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator', 'shift.manage', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
