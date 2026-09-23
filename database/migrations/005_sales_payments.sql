-- Migration 005: Sales + payments (Master Spec 67-81, 102-105, 151-156)
-- GameNet Pro - P1-4

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sequences (
    name    TEXT PRIMARY KEY,
    day     TEXT NOT NULL,
    last_no INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id               TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL REFERENCES customers(id),
    operator_user_id TEXT NOT NULL REFERENCES users(id),
    status           TEXT NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')),
    subtotal         INTEGER NOT NULL,
    discount_pct     INTEGER NOT NULL DEFAULT 0,
    discount_amount  INTEGER NOT NULL DEFAULT 0,
    discount_reason  TEXT,
    total            INTEGER NOT NULL,
    cancel_reason    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    confirmed_at     TEXT,
    cancelled_at     TEXT
);

CREATE TABLE IF NOT EXISTS sale_items (
    id             TEXT PRIMARY KEY,
    sale_id        TEXT NOT NULL REFERENCES sales(id),
    kind           TEXT NOT NULL,
    label          TEXT NOT NULL,
    qty            INTEGER NOT NULL DEFAULT 1,
    unit_price     INTEGER NOT NULL,
    total_price    INTEGER NOT NULL,
    duration_sec   INTEGER,
    pc_class       TEXT,
    ref_id         TEXT,
    price_snapshot TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id           TEXT PRIMARY KEY,
    sale_id      TEXT NOT NULL REFERENCES sales(id),
    method       TEXT NOT NULL CHECK (method IN ('CASH', 'CARD', 'BALANCE')),
    amount       INTEGER NOT NULL,
    tendered     INTEGER,
    status       TEXT NOT NULL DEFAULT 'CREATED'
                 CHECK (status IN ('CREATED', 'PENDING', 'PROCESSING', 'PAID',
                                   'FAILED', 'CANCELLED', 'UNKNOWN',
                                   'REFUND_PENDING', 'REFUNDED')),
    provider     TEXT NOT NULL,
    provider_ref TEXT,
    meta         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    paid_at      TEXT
);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id           TEXT PRIMARY KEY,
    payment_id   TEXT NOT NULL REFERENCES payments(id),
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    provider_ref TEXT,
    amount       INTEGER NOT NULL,
    message      TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_events (
    id          TEXT PRIMARY KEY,
    payment_id  TEXT NOT NULL REFERENCES payments(id),
    from_status TEXT,
    to_status   TEXT NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);
CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_payments_sale ON payments(sale_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
CREATE INDEX IF NOT EXISTS idx_paytx_payment ON payment_transactions(payment_id);
CREATE INDEX IF NOT EXISTS idx_payev_payment ON payment_events(payment_id);

INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES
    ('operator_max_discount_pct', '10', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
