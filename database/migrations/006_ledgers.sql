-- Migration 006: Packages, VIP plans, entitlements, ledgers
-- (Master Spec 35-39, 72-74, 85-87, 111-114, 291-294) - GameNet Pro P1-5
--
-- Ledger tables are append-only: no UPDATE/DELETE API exists for them.
-- Materialized balances (consumed_sec / balance_after) are rebuildable
-- from their ledgers.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS packages (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    duration_sec  INTEGER NOT NULL,
    price         INTEGER NOT NULL,
    bonus_sec     INTEGER NOT NULL DEFAULT 0,
    validity_days INTEGER,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vip_plans (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    duration_days INTEGER NOT NULL,
    price         INTEGER NOT NULL,
    discount_pct  INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entitlements (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    kind         TEXT NOT NULL CHECK (kind IN ('TIME_CREDIT', 'PACKAGE_CREDIT', 'VIP')),
    status       TEXT NOT NULL CHECK (status IN ('PENDING', 'ACTIVE', 'EXPIRED', 'CANCELLED', 'SUSPENDED')),
    granted_sec  INTEGER,
    consumed_sec INTEGER NOT NULL DEFAULT 0,
    starts_at    TEXT NOT NULL,
    expires_at   TEXT,
    discount_pct INTEGER NOT NULL DEFAULT 0,
    sale_id      TEXT REFERENCES sales(id),
    sale_item_id TEXT REFERENCES sale_items(id),
    ref_id       TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entitlement_ledger (
    id               TEXT PRIMARY KEY,
    entitlement_id   TEXT NOT NULL REFERENCES entitlements(id),
    delta_sec        INTEGER NOT NULL,
    balance_after_sec INTEGER NOT NULL,
    kind             TEXT NOT NULL,
    ref_type         TEXT,
    ref_id           TEXT,
    reason           TEXT,
    created_by       TEXT REFERENCES users(id),
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_balance_ledger (
    id            TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    amount        INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    ref_type      TEXT,
    ref_id        TEXT,
    reason        TEXT,
    created_by    TEXT REFERENCES users(id),
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ent_customer ON entitlements(customer_id);
CREATE INDEX IF NOT EXISTS idx_ent_status ON entitlements(customer_id, status);
CREATE INDEX IF NOT EXISTS idx_eled_ent ON entitlement_ledger(entitlement_id);
CREATE INDEX IF NOT EXISTS idx_bled_customer ON customer_balance_ledger(customer_id);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('vip_renewal_mode', 'AFTER_EXPIRY', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('credit_priority',  'EARLIEST_EXPIRY', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
