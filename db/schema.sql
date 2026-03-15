-- ════════════════════════════════════════════════════════════════════════════════
-- SCHEMA - ALL COLUMNS FROM YOUR XLSX
-- ════════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS products (
    id                      TEXT PRIMARY KEY,
    product_name            TEXT NOT NULL,
    weight                  TEXT,
    master_package          TEXT,
    mrp_unit                REAL,
    offer_rate_new          REAL,
    scheme_percentage       TEXT,
    scheme_amount           REAL,
    billing                 REAL,
    tax_18_percent          REAL,
    tax_12_percent          REAL,
    super_total             REAL,
    ss_margin_7_percent     REAL,
    distributor_total       REAL,
    dist_margin_10_percent  REAL,
    retail                  REAL,
    is_active               INTEGER DEFAULT 1
);

-- Indices for fast search
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(product_name);
CREATE INDEX IF NOT EXISTS idx_products_weight ON products(weight);

-- FTS for semantic search
CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
    product_name,
    weight,
    content=products,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS products_ai AFTER INSERT ON products BEGIN
    INSERT INTO products_fts(rowid, product_name, weight)
    VALUES (new.rowid, new.product_name, new.weight);
END;

CREATE TRIGGER IF NOT EXISTS products_ad AFTER DELETE ON products BEGIN
    DELETE FROM products_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS products_au AFTER UPDATE ON products BEGIN
    DELETE FROM products_fts WHERE rowid = old.rowid;
    INSERT INTO products_fts(rowid, product_name, weight)
    VALUES (new.rowid, new.product_name, new.weight);
END;