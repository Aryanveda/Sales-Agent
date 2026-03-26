import os
import re
import json
import logging
import sqlite3
from google import genai
from google.genai import types

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

from agent.prompt import ENTITY_SYSTEM_PROMPT, ENTITY_USER_PROMPT

logger  = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "db/aryanveda.db")

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ── Alias map: Hinglish spoken word → DB keyword ─────────────────────────────
ALIAS_MAP = {
    "amla":           "amla hair oil",
    "amla tel":       "amla hair oil",
    "badam":          "almond hair oil",
    "badam tel":      "almond hair oil",
    "almond":         "almond hair oil",
    "cool cool":      "cool cool hair oil",
    "thanda tel":     "cool cool hair oil",
    "divyaratna":     "cool cool hair oil",
    "colour plus":    "colour plus",
    "color plus":     "colour plus",
    "keshsilk":       "keshsilk",
    "kesh silk":      "kesh silk",
    "rosemary":       "rosemary hair",
    "kerala":         "kerala ayurvedic",
    "himaryan":       "himaryan",
    "coconut":        "coconut",
    "olive":          "olive",
    "boroneem":       "boroneem",
    "x-ice":          "x-ice",
    "xice":           "x-ice",
    "silk plus":      "silk plus",
    "fruit glow":     "fruit glow",
    "fruitglow":      "fruit glow",
    "gold bleach":    "gold bleach",
    "bleach":         "bleach",
    "vasojelly":      "vasojelly",
    "vaso jelly":     "vasojelly",
    "strawberry":     "strawberry",
    "cocoa":          "cocoa",
    "petroleum":      "petroleum jelly",
    "petro jelly":    "petroleum jelly",
    "pj":             "petroleum jelly",
    "gulab jal":      "gulab jal",
    "rose water":     "rose water",
    "sunscreen":      "sunscreen",
    "sunblock":       "sunscreen",
    "spf":            "sunscreen",
    "glycerin":       "glycerin",
    "glicerin":       "glycerin",
    "turmeric":       "turmeric",
    "haldi":          "turmeric",
    "aloevera":       "aloevera",
    "aloe":           "aloevera",
    "honey almond":   "honey",
    "shahad badam":   "honey",
    "oats":           "oats",
    "moisturiser":    "oats",
    "brilliantine":   "brilliantine",
    "hair spray":     "hair spray",
    "lip guard":      "lip guard",
    "lip jelly":      "lip jelly",
    "green apple":    "green apple",
    "protine":        "protine",
    "herbal shampoo": "herbal",
    "neem shampoo":   "herbal",
    "hair removing":  "hair removing",
    "hair removal":   "hair removing",
    "charcoal":       "charcoal",
    "ubtan":          "ubtan",
    "vitamin c":      "vitamin c",
    "papaya":         "papaya",
    "apple face":     "apple face wash",
    "neem tulsi":     "neem tulsi",
    "himaryan":       "himaryan",
    "jasmine":        "coconut jasmine",
    "coconut jasmine":"coconut jasmine",
}

WEIGHT_ALIASES = {
    # Hindi/Hinglish size words
    "choti":           "small",
    "chhoti":          "small",
    "chota":           "small",
    "chhota":          "small",
    "chhoti wali":     "small",
    "choti wali":      "small",
    "sabse chota":     "small",
    "sabse chhota":    "small",
    "badi":            "large",
    "bari":            "large",
    "bada":            "large",
    "badi wali":       "large",
    "bara wala":       "large",
    "sabse badi":      "large",
    "sabse bada":      "large",
    "large":           "large",
    "small":           "small",
    "medium":          "medium",
    "medium wala":     "medium",
    "beech wala":      "medium",
    "badi wali":       "large",
    "choti wali":      "small",
    "chhoti wali":     "small",
    "bade wale":       "large",
    "chote wale":      "small",
    # Variant/type/variety/size — caller wants to see options, not a specific size
    # _normalise_weight returns None for these → triggers clarification
    "variant":         "__ask__",
    "variants":        "__ask__",
    "variety":         "__ask__",
    "varieties":       "__ask__",
    "type":            "__ask__",
    "types":           "__ask__",
    "size":            "__ask__",
    "sizes":           "__ask__",
    "pack":            "__ask__",
    "kaunsa variant":  "__ask__",
    "kaun sa variant": "__ask__",
    "kaunsi variety":  "__ask__",
    "kaunsa size":     "__ask__",
    "kaun sa size":    "__ask__",
    "kaunsa type":     "__ask__",
    "kaun kaun se":    "__ask__",
    "sab size":        "__ask__",
    "sare size":       "__ask__",
    "kitne size":      "__ask__",
    "kitne variant":   "__ask__",
    "variety batao":   "__ask__",
    "variants batao":  "__ask__",
    "size batao":      "__ask__",
}

_SIZE_PATTERN = re.compile(
    r'(\d+\.?\d*)\s*(ml|gm|g|gram|grams|litre|liter|l|kg|kilo|mm)?',
    re.IGNORECASE
)

_UNIT_MAP = {
    "ml": "ml", "g": "gm", "gm": "gm",
    "gram": "gm", "grams": "gm",
    "l": "l", "litre": "l", "liter": "l",
    "kg": "kg", "kilo": "kg",
}

_ASK_TRIGGERS = [
    "variant", "variety", "type", "size", "pack",
    "kaun", "kitne", "sab ", "sare", "batao"
]


# ── DB helpers ────────────────────────────────────────────────────────────────

def _normalise_weight(hint: str):
    """
    Normalise any size/variant phrase to a DB-matchable string.
    Returns:
      - A size string like "180 ml", "100gm", "small", "large"
      - None  → caller wants to see all variants (triggers clarification)
      - Raw hint → let DB fuzzy-match handle it
    """
    if not hint:
        return hint
    h = hint.lower().strip()

    # Direct alias lookup
    mapped = WEIGHT_ALIASES.get(h)
    if mapped == "__ask__":
        return None
    if mapped:
        return mapped

    # Partial phrase — caller asking about options
    if any(t in h for t in _ASK_TRIGGERS):
        return None

    # Numeric extraction — "180ml", "90 ml", "100 gram"
    m = _SIZE_PATTERN.search(h)
    if m:
        num  = m.group(1)
        unit = _UNIT_MAP.get((m.group(2) or "").lower().strip(),
                              (m.group(2) or "").lower().strip())
        return f"{num} {unit}".strip() if unit else num

    return h


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


def _all_products_catalog() -> str:
    """Return a compact product catalog string for the LLM prompt."""
    try:
        conn = _db_conn()
        rows = conn.execute(
            "SELECT id, product_name, weight FROM products WHERE is_active=1 ORDER BY product_name, weight"
        ).fetchall()
        conn.close()
        return "\n".join(f"{r['id']} | {r['product_name']} | {r['weight']}" for r in rows)
    except Exception as e:
        logger.error(f"[Entities] catalog fetch failed: {e}")
        return ""


def _sql_match(product_name: str, weight_hint: str) -> list[dict]:
    name_lc  = product_name.lower().strip()
    keywords = []

    for alias in sorted(ALIAS_MAP, key=len, reverse=True):
        if alias in name_lc:
            keywords.append(ALIAS_MAP[alias])
            break

    if not keywords:
        stop = {"ka", "ki", "ke", "hai", "kya", "wala", "wali", "waale",
                "tel", "oil", "me", "mein", "aur", "or", "ek", "do",
                "sir", "ji", "aapka", "mujhe", "chahiye"}
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
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    if not weight_hint:
        return None

    # _normalise_weight returns None when caller says "variant/type/size"
    # meaning they want to see options — treat as no weight specified
    normalised = _normalise_weight(weight_hint)
    if not normalised:
        return None
    w = normalised.lower()

    exact = [r for r in rows if w in (r.get("weight") or "").lower()]
    if exact:
        return exact[0]

    digits = re.sub(r"[^\d]", "", w)
    if digits:
        digit_match = [r for r in rows if digits in re.sub(r"[^\d]", "", (r.get("weight") or ""))]
        if digit_match:
            return digit_match[0]

    return None


# ── LLM fallback for ambiguous / unmatched cases ─────────────────────────────

def _llm_match(product_name: str, weight_hint: str) -> dict:
    """
    Use ENTITY_SYSTEM_PROMPT from prompt.py to resolve ambiguous product mentions.
    Called only when SQL matching fails or returns ambiguous results.
    """
    catalog = _all_products_catalog()
    if not catalog:
        return {}

    prompt = ENTITY_USER_PROMPT.format(
        product_name = product_name,
        weight_hint  = weight_hint or "not specified",
    )
    # Escape literal braces in the prompt before .format() so the JSON
    # example line doesn't get misread as a template slot
    safe_prompt = ENTITY_SYSTEM_PROMPT.replace("{", "{{").replace("}", "}}")
    # Re-open only the actual placeholder we want to fill
    safe_prompt = safe_prompt.replace("{{product_catalog}}", "{product_catalog}")
    system = safe_prompt.format(product_catalog=catalog)

    try:
        response = _client.models.generate_content(
            model    = "gemini-2.5-flash",
            contents = prompt,
            config   = types.GenerateContentConfig(
                system_instruction = system,
                temperature        = 0.1,
                max_output_tokens  = 200,
                thinking_config    = types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = response.text or ""
        start = raw.find("{")
        end   = raw.rfind("}")
        if start != -1 and end != -1:
            result = json.loads(raw[start:end + 1])
            logger.info(
                f"[Entities-LLM] matched id={result.get('product_id')} "
                f"conf={result.get('confidence')}"
            )
            return result
    except Exception as e:
        logger.warning(f"[Entities-LLM] failed: {e}")
    return {}


# ── EntityResolver ────────────────────────────────────────────────────────────

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

        # Step 1: SQL match
        rows   = _sql_match(product_name, weight_hint)
        picked = _pick_variant(rows, weight_hint) if rows else None

        # Step 2: if SQL matched exactly — return full row
        if picked:
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
                f"[Entities] matched id={resolved['product_id']} "
                f"name='{resolved['product_name']}' weight='{resolved['weight']}'"
            )
            return resolved

        # Step 3: SQL ambiguous or no match → try LLM
        logger.info(f"[Entities] SQL {'ambiguous' if rows else 'no match'} for '{product_name}' — trying LLM")
        llm_result = _llm_match(product_name, weight_hint)

        if llm_result.get("product_id"):
            full = _full_row(llm_result["product_id"])
            if full:
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
                    "confidence":     llm_result.get("confidence", 0.8),
                    "quantity":       raw_entities.get("quantity"),
                    "order_ref":      raw_entities.get("order_ref"),
                }
                logger.info(
                    f"[Entities-LLM] resolved id={resolved['product_id']} "
                    f"name='{resolved['product_name']}'"
                )
                return resolved

        # Step 4: still ambiguous — return candidates for agent to ask
        if rows:
            candidates = [f"{r['id']}:{r['product_name']} {r.get('weight','')}" for r in rows]
            logger.info(f"[Entities] ambiguous — {len(rows)} variants, weight needed")
            return {
                **self._empty(raw_entities),
                "product_name": rows[0]["product_name"],
                "candidates":   candidates,
                "confidence":   0.7,
            }

        # Step 5: genuinely not found
        logger.info(f"[Entities] No match for '{product_name}'")
        return self._empty(raw_entities)

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