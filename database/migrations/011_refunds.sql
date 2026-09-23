-- P3-2: refunds (money out + credit clawback). Uses the existing
-- `sales.refund` permission. Cash refunds ride the open shift's drawer
-- (auto OUT movement); BALANCE refunds credit the customer back.

CREATE TABLE IF NOT EXISTS refunds (
    id         TEXT PRIMARY KEY,
    sale_id    TEXT NOT NULL REFERENCES sales(id),
    amount     INTEGER NOT NULL CHECK (amount > 0),
    method     TEXT NOT NULL CHECK (method IN ('CASH', 'BALANCE')),
    reason     TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    shift_id   TEXT REFERENCES shifts(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refunds_sale ON refunds(sale_id);
