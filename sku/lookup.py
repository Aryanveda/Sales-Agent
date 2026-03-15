import os
import time
import uuid
import sqlite3
import logging
from dotenv import load_dotenv

load_dotenv()

logger    = logging.getLogger(__name__)
CACHE_TTL = 300
DB_PATH   = os.getenv("DB_PATH", "db/aryaveda.db")


class SKULookup:
    def __init__(self):
        self.db_path = DB_PATH
        self._cache  = {}

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _query(self, sql: str, params: tuple = ()) -> list:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def _cache_get(self, key: str):
        entry = self._cache.get(key)
        if entry and time.time() - entry["ts"] < CACHE_TTL:
            return entry["data"]
        return None

    def _cache_set(self, key: str, data):
        self._cache[key] = {"data": data, "ts": time.time()}

    def check_stock(self, sku_code: str, distributor_code: str) -> dict | None:
        key    = f"stock:{sku_code}:{distributor_code}"
        cached = self._cache_get(key)
        if cached:
            return cached

        rows = self._query("""
            SELECT
                s.sku_code,
                s.name,
                s.unit,
                ds.stock_qty,
                COALESCE(ds.price_override, s.base_price) AS price,
                d.name AS dist_name,
                d.code AS dist_code
            FROM distributor_skus ds
            JOIN skus         s ON ds.sku_id         = s.id
            JOIN distributors d ON ds.distributor_id  = d.id
            WHERE s.sku_code = ?
              AND d.code     = ?
              AND s.is_active = 1
              AND d.is_active = 1
        """, (sku_code, distributor_code))

        result = rows[0] if rows else None
        if result:
            self._cache_set(key, result)
        return result

    def get_price(self, sku_code: str, distributor_code: str) -> dict | None:
        key    = f"price:{sku_code}:{distributor_code}"
        cached = self._cache_get(key)
        if cached:
            return cached

        rows = self._query("""
            SELECT
                s.name,
                s.unit,
                s.mrp,
                COALESCE(ds.price_override, s.base_price) AS price,
                d.name AS dist_name
            FROM distributor_skus ds
            JOIN skus         s ON ds.sku_id        = s.id
            JOIN distributors d ON ds.distributor_id = d.id
            WHERE s.sku_code = ?
              AND d.code     = ?
        """, (sku_code, distributor_code))

        result = rows[0] if rows else None
        if result:
            self._cache_set(key, result)
        return result

    def list_skus(self, distributor_code: str) -> dict:
        key    = f"list:{distributor_code}"
        cached = self._cache_get(key)
        if cached:
            return cached

        rows = self._query("""
            SELECT
                s.sku_code,
                s.name,
                s.category,
                s.unit,
                ds.stock_qty,
                COALESCE(ds.price_override, s.base_price) AS price,
                d.name AS dist_name
            FROM distributor_skus ds
            JOIN skus         s ON ds.sku_id        = s.id
            JOIN distributors d ON ds.distributor_id = d.id
            WHERE d.code      = ?
              AND s.is_active = 1
              AND ds.stock_qty > 0
            ORDER BY s.category, s.name
        """, (distributor_code,))

        result = {
            "dist_name": rows[0]["dist_name"] if rows else distributor_code,
            "skus":      rows
        }
        self._cache_set(key, result)
        return result

    def place_order(self, sku_code: str, distributor_code: str, quantity: int, session_id: str = None) -> dict:
        order_ref = f"AV-{uuid.uuid4().hex[:8].upper()}"

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO orders (id, order_ref, session_id, distributor_id, sku_id,
                                    quantity, unit_price, total_amount, status, placed_via)
                SELECT
                    ?, ?, ?,
                    d.id, s.id,
                    ?,
                    COALESCE(ds.price_override, s.base_price),
                    COALESCE(ds.price_override, s.base_price) * ?,
                    'pending', 'voice'
                FROM distributor_skus ds
                JOIN skus         s ON ds.sku_id        = s.id
                JOIN distributors d ON ds.distributor_id = d.id
                WHERE s.sku_code = ?
                  AND d.code     = ?
            """, (str(uuid.uuid4()), order_ref, session_id, quantity, quantity, sku_code, distributor_code))

        logger.info(f"[Order] placed {order_ref} — {quantity}x {sku_code} @ {distributor_code}")
        return {"order_ref": order_ref, "status": "pending"}

    def get_order_status(self, order_ref: str) -> dict | None:
        rows = self._query("""
            SELECT
                o.order_ref,
                o.quantity,
                o.status,
                o.placed_at,
                o.total_amount,
                s.name AS sku_name,
                d.name AS dist_name
            FROM orders       o
            JOIN skus         s ON o.sku_id         = s.id
            JOIN distributors d ON o.distributor_id = d.id
            WHERE o.order_ref = ?
        """, (order_ref,))

        return rows[0] if rows else None

    def fetch_distributors(self):
        return self._query("""
            SELECT code, name, name_hindi FROM distributors WHERE is_active = 1
        """)