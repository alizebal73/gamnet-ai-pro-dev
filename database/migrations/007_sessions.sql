-- Migration 007: Sessions + PC history (Master Spec 25-31, 157-166, 215-216)
-- GameNet Pro - P1-6
--
-- One-active-session rules (Spec 30/215) are enforced by partial unique
-- indexes, so races fail safely at the database level too.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(id),
    pc_id               TEXT REFERENCES pcs(id),
    status              TEXT NOT NULL DEFAULT 'CREATED'
                        CHECK (status IN ('CREATED', 'AUTHORIZED', 'ACTIVE', 'PAUSED',
                                          'ENDED', 'CANCELLED', 'INTERRUPTED',
                                          'CONNECTION_LOST')),
    created_by          TEXT REFERENCES users(id),
    started_at          TEXT,
    last_accounted_at   TEXT,
    ended_at            TEXT,
    ended_reason        TEXT,
    total_consumed_sec  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_events (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    kind        TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    pc_id       TEXT REFERENCES pcs(id),
    actor_user_id TEXT REFERENCES users(id),
    reason      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_consumptions (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL REFERENCES sessions(id),
    entitlement_id TEXT REFERENCES entitlements(id),
    seconds        INTEGER NOT NULL,
    period_start   TEXT NOT NULL,
    period_end     TEXT NOT NULL,
    kind           TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pc_status_history (
    id            TEXT PRIMARY KEY,
    pc_id         TEXT NOT NULL REFERENCES pcs(id),
    from_status   TEXT,
    to_status     TEXT NOT NULL,
    reason        TEXT,
    actor_user_id TEXT REFERENCES users(id),
    created_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_session_customer ON sessions(customer_id)
    WHERE status IN ('AUTHORIZED', 'ACTIVE', 'PAUSED', 'INTERRUPTED', 'CONNECTION_LOST');
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_session_pc ON sessions(pc_id)
    WHERE pc_id IS NOT NULL
      AND status IN ('AUTHORIZED', 'ACTIVE', 'PAUSED', 'INTERRUPTED', 'CONNECTION_LOST');
CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(customer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_pc ON sessions(pc_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sevt_session ON session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_scon_session ON session_consumptions(session_id);
CREATE INDEX IF NOT EXISTS idx_pchist_pc ON pc_status_history(pc_id);

-- Daily-ops permission for sessions (Spec 93 is a minimum list).
INSERT OR IGNORE INTO permissions (name, description, created_at) VALUES
    ('session.operate', 'Operate sessions (start/pause/resume/end/transfer).',
     strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

INSERT OR IGNORE INTO role_permissions (role_id, permission, assigned_at) VALUES
    ('owner',      'session.operate', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('manager',    'session.operate', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('operator',   'session.operate', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('technician', 'session.operate', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
