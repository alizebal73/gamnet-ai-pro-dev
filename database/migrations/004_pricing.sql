-- Migration 004: Pricing rules + store settings seed (Master Spec 70-71, 320)
-- GameNet Pro - P1-3

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pricing_rules (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('PER_HOUR', 'FLAT', 'MULTIPLIER')),
    duration_sec     INTEGER,
    price            INTEGER,
    factor_pct       INTEGER,
    pc_class         TEXT,
    scope            TEXT NOT NULL DEFAULT 'ANY' CHECK (scope IN ('ANY', 'WEEKDAY', 'WEEKEND')),
    window_start_min INTEGER,
    window_end_min   INTEGER,
    priority         INTEGER NOT NULL DEFAULT 100,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pricing_active_kind ON pricing_rules(active, kind);

-- Seed store/pricing settings (Master Spec 320). Money in minor units (RIAL).
INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('store_name',         'GameNet Pro', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('base_currency_unit', 'RIAL',        strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('price_per_hour',     '80000',       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('weekend_days',       '3,4',         strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
