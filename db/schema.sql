CREATE TABLE IF NOT EXISTS distributors (
    id          TEXT PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    name_hindi  TEXT,
    city        TEXT,
    region      TEXT,
    phone       TEXT,
    is_active   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS skus (
    id          TEXT PRIMARY KEY,
    sku_code    TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT,
    unit        TEXT DEFAULT 'piece',
    base_price  REAL,
    mrp         REAL,
    is_active   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS distributor_skus (
    id              TEXT PRIMARY KEY,
    distributor_id  TEXT NOT NULL REFERENCES distributors(id),
    sku_id          TEXT NOT NULL REFERENCES skus(id),
    stock_qty       INTEGER DEFAULT 0,
    price_override  REAL,
    UNIQUE (distributor_id, sku_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id              TEXT PRIMARY KEY,
    order_ref       TEXT UNIQUE NOT NULL,
    session_id      TEXT,
    distributor_id  TEXT REFERENCES distributors(id),
    sku_id          TEXT REFERENCES skus(id),
    quantity        INTEGER NOT NULL,
    unit_price      REAL,
    total_amount    REAL,
    status          TEXT DEFAULT 'pending',
    placed_via      TEXT DEFAULT 'voice',
    placed_at       TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS call_logs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    caller_number   TEXT,
    turn            INTEGER DEFAULT 1,
    transcript      TEXT,
    stt_confidence  REAL,
    intent          TEXT,
    action          TEXT,
    entities        TEXT,
    response_text   TEXT,
    latency_ms      INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);