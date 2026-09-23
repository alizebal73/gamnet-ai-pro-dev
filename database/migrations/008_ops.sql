-- Migration 008: Audit hash chain + reconciliation runs + safe mode
-- (Master Spec 95-96, 145, 225-230, 295, 337-339) - GameNet Pro P1-7

PRAGMA foreign_keys = ON;

ALTER TABLE audit_logs ADD COLUMN prev_hash TEXT;
ALTER TABLE audit_logs ADD COLUMN hash TEXT;

CREATE TABLE IF NOT EXISTS reconciliation_runs (
    id           TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('OK', 'ISSUES', 'ERROR')),
    issues_json  TEXT NOT NULL,
    triggered_by TEXT REFERENCES users(id),
    created_at   TEXT NOT NULL
);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('safe_mode', '0', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('safe_mode_reason', '', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
