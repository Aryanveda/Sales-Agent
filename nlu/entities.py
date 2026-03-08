import os
import json
import logging
import sqlite3
import time
from google import genai
from google.genai import types
from google.genai.errors import ServerError

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv()

logger  = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

ENTITY_SYSTEM_PROMPT = """You are a product-matching engine for an Indian FMCG distributor called AryanVeda/Nimson.

Your job: given a product name as spoken (often garbled Hinglish), find the best matching product from the catalog below and return its ID and canonical name. Also extract the weight/size variant if mentioned.

PRODUCT CATALOG (format: id | product_name | weight):
{product_catalog}

RULES:
1. Match phonetically and semantically. Examples of spoken → catalog matches:
   - "amla tel" / "amla hair oil" → Nimson Amla Hair Oil
   - "colour plus shampoo" / "colour wala shampoo" → New Colour Plus Family Shampoo
   - "nimson almond" / "badam ka tel" → Nimson Almond Hair Oil
   - "cool cool oil" / "divyaratna wala" → Divyaratna Cool Cool Hair Oil
   - "fruit glow cream" / "fruitglow" → Fruit Glow Cream
   - "boroneem talc" / "neem powder" → Nimson Boroneem Talcum Powder
   - "petroleum jelly" / "vaseline wali" → Nimson Ayurvedic Petroleum Jelly
   - "gulab jal" / "rose water" → Gulab Jal Premium Rose water
   - "sunscreen" / "sunblock" → Sunscreen SPF 30 PA++
   - "face wash" (generic) → ask for clarification, return null

2. Weight/size matching — if the caller mentions a size, prefer that variant:
   - "90 ml", "choti wali", "180 ml", "badi wali", "500 ml", "kilo wali" etc.
   - If no size mentioned and multiple sizes exist, return product_id as null and list candidates.

3. If confident (score ≥ 0.7): return the single best match.
4. If ambiguous or no match: return null for product_id.
5. Never invent product IDs. Only use IDs from the catalog above.

Return ONLY valid compact JSON — no markdown, no explanation:
{{"product_id": "<id or null>", "product_name": "<canonical name or null>", "weight": "<matched weight or null>", "confidence": <0.0-1.0>, "candidates": ["<id1>", "<id2>"] }}
candidates should only be populated when product_id is null and there are 2-3 close matches.
"""

ENTITY_USER_PROMPT = """Spoken product mention: "{product_name}"
Size/weight hint: "{weight_hint}"

Match this to the catalog and return JSON."""


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_product_catalog() -> str:
    """Load all active products from the products table."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, product_name, weight FROM products WHERE is_active=1 ORDER BY product_name, weight"
    ).fetchall()
    conn.close()
    lines = "\n".join(f"{r['id']} | {r['product_name']} | {r['weight']}" for r in rows)
    logger.info(f"[Entities] Loaded {len(rows)} products from catalog.")
    return lines


def _extract_json(text: str) -> dict:
    text = text.strip()

    clean = text
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
    if clean.endswith("```"):
        clean = clean.rsplit("```", 1)[0]
    clean = clean.strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    start = clean.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response: {text[:120]!r}")

    depth, in_str, escape = 0, False, False
    end = -1
    for i, ch in enumerate(clean[start:], start):
        if escape:                escape = False; continue
        if ch == "\\" and in_str: escape = True;  continue
        if ch == '"':             in_str = not in_str; continue
        if in_str:                continue
        if ch == "{":             depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end != -1:
        try:
            return json.loads(clean[start:end + 1])
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse failed: {e} | raw: {clean[start:end + 1][:120]!r}")

    logger.warning(f"[Entities] Truncated JSON detected, attempting repair: {clean[start:start+120]!r}")
    fragment = clean[start:]
    open_braces  = fragment.count("{") - fragment.count("}")
    open_brackets = fragment.count("[") - fragment.count("]")
    repaired = fragment + ("]" * max(open_brackets, 0)) + ("}" * max(open_braces, 0))
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        raise ValueError(f"Unrecoverable truncated JSON from Gemini. Raw: {text[:200]!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Entity Resolver
# ─────────────────────────────────────────────────────────────────────────────

class EntityResolver:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model   = model
        self.client  = _client
        self._catalog = _build_product_catalog()

    def resolve(self, raw_entities: dict, retries: int = 3, backoff: float = 2.0) -> dict:
        product_name = (raw_entities.get("product_name") or "").strip()
        weight_hint  = (raw_entities.get("weight_hint") or
                        raw_entities.get("weight") or "").strip()

        if not product_name:
            logger.info("[Entities] No product name to resolve.")
            return self._empty(raw_entities)

        for attempt in range(1, retries + 1):
            try:
                system = ENTITY_SYSTEM_PROMPT.format(product_catalog=self._catalog)
                user   = ENTITY_USER_PROMPT.format(
                    product_name=product_name,
                    weight_hint=weight_hint if weight_hint else "not specified",
                )

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0,
                        max_output_tokens=512,
                        response_mime_type="application/json",
                    ),
                )

                raw = response.text or ""
                if not raw and response.candidates:
                    raw = "".join(
                        p.text for p in response.candidates[0].content.parts
                        if hasattr(p, "text") and p.text
                    )

                result = _extract_json(raw)

                product_id = result.get("product_id")
                db_row     = None
                if product_id:
                    db_row = self._fetch_product(product_id)

                resolved = {
                    "product_id":   product_id,
                    "product_name": db_row["product_name"] if db_row else result.get("product_name"),
                    "weight":       db_row["weight"]       if db_row else result.get("weight"),
                    "mrp_unit":     db_row["mrp_unit"]     if db_row else None,
                    "offer_rate":   db_row["offer_rate_new"] if db_row else None,
                    "candidates":   result.get("candidates", []),
                    "confidence":   result.get("confidence", 0.0),
                    "quantity":     raw_entities.get("quantity"),
                    "order_ref":    raw_entities.get("order_ref"),
                }

                logger.info(
                    f"[Entities] product_id={resolved['product_id']} "
                    f"name='{resolved['product_name']}' weight='{resolved['weight']}' "
                    f"confidence={resolved['confidence']}"
                )
                return resolved

            except ServerError as e:
                if attempt < retries:
                    wait = backoff * attempt
                    print(f"  [retry {attempt}/{retries}] Gemini 503 — retrying in {wait:.0f}s...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"  [error] Gemini unavailable after {retries} attempts: {e}", flush=True)

            except Exception as e:
                print(f"  [error] entity resolve failed: {type(e).__name__}: {e}", flush=True)
                return self._empty(raw_entities)

        return self._empty(raw_entities)

    def _fetch_product(self, product_id: str) -> dict | None:
        """Fetch a product row by ID."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"[Entities] DB fetch failed for {product_id}: {e}")
            return None

    def _empty(self, raw: dict = None) -> dict:
        return {
            "product_id":   None,
            "product_name": None,
            "weight":       None,
            "mrp_unit":     None,
            "offer_rate":   None,
            "candidates":   [],
            "confidence":   0.0,
            "quantity":     raw.get("quantity")  if raw else None,
            "order_ref":    raw.get("order_ref") if raw else None,
        }