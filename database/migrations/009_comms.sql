-- P2-1: agent channel core (device auth tokens, command queue, PC presence columns).
-- Master Spec: device auth separate from customer (135), heartbeat protocol
-- (326-328), remote command execution with ACK (121-123).

CREATE TABLE IF NOT EXISTS agent_tokens (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    pc_id TEXT NOT NULL REFERENCES pcs(id),
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    last_seen_at TEXT,
    agent_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_pc ON agent_tokens(pc_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash ON agent_tokens(token_hash);

CREATE TABLE IF NOT EXISTS agent_commands (
    id TEXT PRIMARY KEY,
    pc_id TEXT NOT NULL REFERENCES pcs(id),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_by TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    acked_at TEXT,
    expires_at TEXT NOT NULL,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_commands_pc_status ON agent_commands(pc_id, status);

-- NOTE: pcs.last_seen_at / pcs.agent_version already exist in 001_initial.

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('agent_lease_sec', '45', '2026-01-01T00:00:00'),
    ('agent_token_ttl_hours', '24', '2026-01-01T00:00:00'),
    ('agent_command_ttl_sec', '300', '2026-01-01T00:00:00');
