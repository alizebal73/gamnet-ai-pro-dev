-- P3-3: snack/bar inventory + append-only stock ledger.
-- FOOD sale items reference inventory_items; stock is decremented at sale
-- confirm time (activation), never at draft time.

CREATE TABLE IF NOT EXISTS inventory_items (
    id           TEXT PRIMARY KEY,
    sku          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    unit_price   INTEGER NOT NULL CHECK (unit_price >= 0),
    stock_qty    INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    low_stock_at INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'ACTIVE'
                 CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_ledger (
    id            TEXT PRIMARY KEY,
    item_id       TEXT NOT NULL REFERENCES inventory_items(id),
    delta         INTEGER NOT NULL CHECK (delta != 0),
    balance_after INTEGER NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('RECEIVE', 'SELL', 'ADJUST')),
    ref_type      TEXT,
    ref_id        TEXT,
    reason        TEXT,
    created_by    TEXT REFERENCES users(id),
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_ledger_item ON stock_ledger(item_id);
