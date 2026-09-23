-- P3-5: customer login sessions + customer auth settings.
-- (customer_auth with failed_attempts/locked_until already exists.)

CREATE TABLE IF NOT EXISTS customer_sessions (
    token_hash  TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT,
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_customer_sessions_customer
    ON customer_sessions(customer_id);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('customer_token_ttl_hours', '12', '2026-01-01T00:00:00'),
    ('customer_max_attempts', '5', '2026-01-01T00:00:00'),
    ('customer_lockout_min', '15', '2026-01-01T00:00:00');
