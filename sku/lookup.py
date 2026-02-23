import os
import json
import time
import logging
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

CACHE_TTL = 300  # seconds
class SKULookup:
    def __init__(self):
        self.db    = self._connect_db()
        self._cache = {}

    def _connect_db(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", 5432),
            dbname=os.getenv("DB_NAME", "aryaveda"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
        )

    def _query(self, sql: str, params: tuple = ()) -> list:
        with self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        
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
                d.name  AS dist_name,
                d.code  AS dist_code
            FROM distributor_skus ds
            JOIN skus         s ON ds.sku_id         = s.id
            JOIN distributors d ON ds.distributor_id  = d.id
            WHERE s.sku_code = %s
              AND d.code     = %s
              AND s.is_active = TRUE
              AND d.is_active = TRUE
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
            WHERE s.sku_code = %s
              AND d.code     = %s
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
            WHERE d.code      = %s
              AND s.is_active = TRUE
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
        import uuid
        order_ref = f"AV-{uuid.uuid4().hex[:8].upper()}"

        with self.db.cursor() as cur:
            cur.execute("""
                INSERT INTO orders (order_ref, session_id, distributor_id, sku_id, quantity, unit_price, total_amount, status, placed_via)
                SELECT
                    %s, %s,
                    d.id,
                    s.id,
                    %s,
                    COALESCE(ds.price_override, s.base_price),
                    COALESCE(ds.price_override, s.base_price) * %s,
                    'pending',
                    'voice'
                FROM distributor_skus ds
                JOIN skus         s ON ds.sku_id        = s.id
                JOIN distributors d ON ds.distributor_id = d.id
                WHERE s.sku_code = %s
                  AND d.code     = %s
            """, (order_ref, session_id, quantity, quantity, sku_code, distributor_code))
            self.db.commit()

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
                s.name      AS sku_name,
                d.name      AS dist_name
            FROM orders       o
            JOIN skus         s ON o.sku_id         = s.id
            JOIN distributors d ON o.distributor_id = d.id
            WHERE o.order_ref = %s
        """, (order_ref,))

        return rows[0] if rows else None