-- P4-2: alert inbox + alert/telegram settings.

CREATE TABLE IF NOT EXISTS alerts (
    id          TEXT PRIMARY KEY,
    severity    TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT,
    entity_type TEXT,
    entity_id   TEXT,
    status      TEXT NOT NULL DEFAULT 'OPEN'
                CHECK (status IN ('OPEN', 'ACKED', 'RESOLVED')),
    created_at  TEXT NOT NULL,
    acked_at    TEXT,
    acked_by    TEXT REFERENCES users(id),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_source_entity
    ON alerts(source, entity_type, entity_id);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('telegram_bot_token', '', '2026-01-01T00:00:00'),
    ('telegram_chat_id', '', '2026-01-01T00:00:00'),
    ('alert_disk_min_mb', '2048', '2026-01-01T00:00:00'),
    ('alert_pc_offline_min', '10', '2026-01-01T00:00:00'),
    ('alert_shift_max_hours', '16', '2026-01-01T00:00:00'),
    ('alert_login_spike', '10', '2026-01-01T00:00:00'),
    ('alert_login_window_min', '15', '2026-01-01T00:00:00');
