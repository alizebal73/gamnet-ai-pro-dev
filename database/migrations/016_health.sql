-- P4-3: PC health history (Spec 56: cpu/mem/disk + temperature).

CREATE TABLE IF NOT EXISTS pc_health (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pc_id        TEXT NOT NULL REFERENCES pcs(id),
    cpu_pct      REAL,
    mem_pct      REAL,
    disk_free_mb INTEGER,
    temp_c       REAL,
    recorded_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pc_health_pc_time
    ON pc_health(pc_id, recorded_at);
