-- Migration 003: Idempotency keys (Master Spec 79)
-- GameNet Pro - P1-2
--
-- The key row is written in the SAME transaction as the business effect,
-- so a crash can never leave "effect without record" or vice versa.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS idempotency_keys (
    request_id     TEXT PRIMARY KEY,
    action         TEXT NOT NULL,
    request_hash   TEXT NOT NULL,
    status_code    INTEGER,
    response_body  TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_idempotency_action ON idempotency_keys(action);
