import os
import re
import logging
import sqlite3

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

logger  = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")

# Hinglish → canonical product name keyword map.
# Keys are lowercase tokens the caller might say.
# Values are the canonical product_name substrings to match in the DB.
ALIAS_MAP = {
    "amla":          "amla hair oil",
    "amla tel":      "amla hair oil",
    "badam":         "almond hair oil",
    "badam tel":     "almond hair oil",
    "almond":        "almond hair oil",
    "cool cool":     "cool cool hair oil",
    "thanda tel":    "cool cool hair oil",
    "divyaratna":    "cool cool hair oil",
    "colour plus":   "colour plus",
    "color plus":    "colour plus",
    "keshsilk":      "keshsilk",
    "kesh silk":     "kesh silk",
    "rosemary":      "rosemary hair",
    "kerala":        "kerala ayurvedic",
    "himaryan":      "himaryan",
    "coconut":       "coconut",
    "olive":         "olive",
    "boroneem":      "boroneem",
    "x-ice":         "x-ice",
    "xice":          "x-ice",
    "silk plus":     "silk plus",
    "fruit glow":    "fruit glow",
    "fruitglow":     "fruit glow",
    "gold bleach":   "gold bleach",
    "bleach":        "bleach",
    "vasojelly":     "vasojelly",
    "vaso jelly":    "vasojelly",
    "strawberry":    "strawberry",
    "cocoa":         "cocoa",
    "petroleum":     "petroleum jelly",
    "petro jelly":   "petroleum jelly",
    "pj":            "petroleum jelly",
    "gulab jal":     "gulab jal",
    "rose water":    "rose water",
    "sunscreen":     "sunscreen",
    "sunblock":      "sunscreen",
    "spf":           "sunscreen",
    "glycerin":      "glycerin",
    "glicerin":      "glycerin",
    "turmeric":      "turmeric",
    "haldi":         "turmeric",
    "aloevera":      "aloevera",
    "aloe":          "aloevera",
    "honey almond":  "honey",
    "shahad badam":  "honey",
    "oats":          "oats",
    "moisturiser":   "oats",
    "brilliantine":  "brilliantine",
    "hair spray":    "hair spray",
    "lip guard":     "lip guard",
    "lip jelly":     "lip jelly",
    "green apple":   "green apple",
    "protine":       "protine",
    "herbal shampoo":"herbal",
    "neem shampoo":  "herbal",
    "hair removing": "hair removing",
    "hair removal":  "hair removing",
}

# Weight token normalisation — what a caller says → what's stored in DB
WEIGHT_ALIASES = {
    "choti":  "small",
    "chhoti": "small",
    "badi":   "large",
    "bari":   "large",
}


def _normalise_weight(hint: str) -> str:
    """Normalise caller weight hint to a consistent lookup string."""
    h = hint.lower().strip()
    return WEIGHT_ALIASES.get(h, h)


def _db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _full_row(product_id: str) -> dict:
    try:
        conn = _db_conn()
        row  = conn.execute(
            "SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        logger.error(f"[Entities] DB fetch failed for {product_id}: {e}")
        return {}


def _sql_match(product_name: str, weight_hint: str) -> list[dict]:
    """
    Return matching product rows from the DB using keyword search.
    1. Resolve alias → canonical keyword.
    2. LIKE-match on product_name.
    3. If weight_hint given, prefer exact weight match first, fallback to all variants.
    """
    name_lc  = product_name.lower().strip()
    keywords = []

    # Try multi-word aliases first (longest match wins)
    for alias in sorted(ALIAS_MAP, key=len, reverse=True):
        if alias in name_lc:
            keywords.append(ALIAS_MAP[alias])
            break

    # Fallback: use meaningful words from the raw name itself
    if not keywords:
        stop = {"ka", "ki", "ke", "hai", "kya", "wala", "wali", "waale",
                "tel", "oil", "me", "mein", "aur", "or", "ek", "do"}
        keywords = [w for w in re.split(r"\s+", name_lc) if len(w) > 2 and w not in stop]

    if not keywords:
        return []

    try:
        conn   = _db_conn()
        clause = " AND ".join(f"LOWER(product_name) LIKE ?" for _ in keywords)
        params = [f"%{k}%" for k in keywords]
        rows   = conn.execute(
            f"SELECT * FROM products WHERE {clause} AND is_active=1 ORDER BY product_name, weight",
            params
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"[Entities] SQL match failed: {e}")
        return []


def _pick_variant(rows: list[dict], weight_hint: str) -> dict | None:
    """
    Given a list of matching rows, pick the best weight variant.
    Returns the matched row or None if ambiguous.
    """
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]

    if not weight_hint:
        return None  # multiple variants, no hint — caller must specify

    w = _normalise_weight(weight_hint).lower()

    # Exact substring match on weight column
    exact = [r for r in rows if w in (r.get("weight") or "").lower()]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]  # take closest

    # Fuzzy: try just the numeric part
    digits = re.sub(r"[^\d]", "", w)
    if digits:
        digit_match = [r for r in rows if digits in re.sub(r"[^\d]", "", (r.get("weight") or ""))]
        if digit_match:
            return digit_match[0]

    return None


class EntityResolver:
    def __init__(self):
        self._history: list[dict] = []

    def share_history(self, history: list[dict]) -> None:
        self._history = history

    def resolve(self, raw_entities: dict) -> dict:
        product_name = (raw_entities.get("product_name") or "").strip()
        weight_hint  = (raw_entities.get("weight_hint") or raw_entities.get("weight") or "").strip()

        if not product_name:
            logger.info("[Entities] No product_name — returning empty")
            return self._empty(raw_entities)

        rows = _sql_match(product_name, weight_hint)

        if not rows:
            logger.info(f"[Entities] No DB match for '{product_name}'")
            return self._empty(raw_entities)

        picked = _pick_variant(rows, weight_hint)

        if picked:
            # Exact match — fetch full row for all pricing fields
            full = _full_row(picked["id"])
            resolved = {
                "product_id":     full.get("id"),
                "product_name":   full.get("product_name"),
                "weight":         full.get("weight"),
                "mrp_unit":       full.get("mrp_unit"),
                "offer_rate":     full.get("offer_rate_new"),
                "retail":         full.get("retail"),
                "billing":        full.get("billing"),
                "tax_18_percent": full.get("tax_18_percent"),
                "tax_12_percent": full.get("tax_12_percent"),
                "candidates":     [],
                "confidence":     1.0,
                "quantity":       raw_entities.get("quantity"),
                "order_ref":      raw_entities.get("order_ref"),
            }
            logger.info(
                f"[Entities] matched product_id={resolved['product_id']} "
                f"name='{resolved['product_name']}' weight='{resolved['weight']}'"
            )
            return resolved

        # Multiple variants, no weight — return candidates so the agent can ask
        candidates = [f"{r['id']}:{r['product_name']} {r.get('weight','')}" for r in rows]
        logger.info(f"[Entities] ambiguous — {len(rows)} variants, weight needed")
        return {
            **self._empty(raw_entities),
            "product_name": rows[0]["product_name"],
            "candidates":   candidates,
            "confidence":   0.7,
        }

    def reset(self) -> None:
        self._history.clear()

    def _empty(self, raw: dict = None) -> dict:
        return {
            "product_id":     None,
            "product_name":   None,
            "weight":         None,
            "mrp_unit":       None,
            "offer_rate":     None,
            "retail":         None,
            "billing":        None,
            "tax_18_percent": None,
            "tax_12_percent": None,
            "candidates":     [],
            "confidence":     0.0,
            "quantity":       raw.get("quantity") if raw else None,
            "order_ref":      raw.get("order_ref") if raw else None,
        }