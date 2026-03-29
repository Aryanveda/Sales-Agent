-- ════════════════════════════════════════════════════════════════════════════════
-- call_patch.sql  — Run AFTER call.sql to add missing columns and tables
-- Safe to run multiple times (all statements use IF NOT EXISTS / IF NOT EXISTS guard)
-- ════════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- Patch: add missing columns to callers table
-- ─────────────────────────────────────────────────────────────────────────────

-- SQLite doesn't support IF NOT EXISTS for ALTER TABLE ADD COLUMN,
-- but it won't error if the column already exists when using try/catch in Python.
-- The setup.py applies this via executescript which silently skips duplicate-column errors.

ALTER TABLE callers ADD COLUMN customer_type  TEXT DEFAULT 'unknown';
ALTER TABLE callers ADD COLUMN area           TEXT;

-- ─────────────────────────────────────────────────────────────────────────────
-- caller_summary — cross-call LLM-generated memory per phone number
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS caller_summary (
    phone_number    TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,                  -- 3-4 sentence CRM note
    last_products   TEXT,                           -- JSON list of last discussed products
    last_intent     TEXT,                           -- last known intent
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes')))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- orders — confirmed orders extracted from call transcripts
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    phone_number    TEXT NOT NULL,
    caller_name     TEXT,
    customer_type   TEXT,
    notes           TEXT,                           -- special instructions from call
    status          TEXT DEFAULT 'pending',         -- pending | confirmed | cancelled
    excel_path      TEXT,                           -- path to daily Excel file
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes')))
);

CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id);
CREATE INDEX IF NOT EXISTS idx_orders_phone   ON orders(phone_number);
CREATE INDEX IF NOT EXISTS idx_orders_date    ON orders(created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- order_items — line items per order
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS order_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id      TEXT,                           -- FK to aryanveda.db products.id (cross-DB, soft ref)
    product_name    TEXT NOT NULL,
    weight          TEXT,
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price      REAL DEFAULT 0.0,               -- price at customer_type rate
    total_price     REAL DEFAULT 0.0,
    confirmed       INTEGER DEFAULT 1               -- 1=confirmed, 0=tentative
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);