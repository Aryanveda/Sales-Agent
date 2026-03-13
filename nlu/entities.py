import os
import json
import logging
import sqlite3
import time
from google import genai
from google.genai import types
from google.genai.errors import ServerError

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


ENTITY_SYSTEM_PROMPT = """You are a product-matching engine for AryanVeda/Nimson herbal products in India.

Your job: given a product name as spoken (often garbled Hinglish), find the best matching product from the catalog and return its ID and canonical name with weight/size variant.

PRODUCT CATALOG (format: id | product_name | weight):
{product_catalog}

RULES:
1. Match phonetically and semantically:
   - "amla tel" / "amla hair oil" → Nimson Amla Hair Oil
   - "colour plus shampoo" / "colour wala" → New Colour Plus Family Shampoo
   - "cool cool oil" / "divyaratna" → Divyaratna Cool Cool Hair Oil
   - "fruit glow" → Fruit Glow Cream or Bleach
   - "boroneem talc" / "neem powder" → Nimson Boroneem Talcum Powder
   - "vasojelly" → Nimson Vasojelly variants
   - "petroleum jelly" / "pj" → Nimson Ayurvedic Petroleum Jelly
   - "gulab jal" / "rose water" → Gulab Jal Premium Rose water
   - "sunscreen" / "sunblock" → Sunscreen SPF 30 PA++
   - "face wash" (generic) → ask for clarification, return null

2. Weight/size matching:
   - If caller mentions a size, prefer that variant: "90 ml", "180 ml", "500 ml", "100 gm", etc.
   - If no size mentioned and multiple sizes exist, return null with candidates

3. Confidence scoring:
   - Exact match (including weight) → 0.9-1.0
   - Product match, weight ambiguous → 0.7-0.85
   - Generic or unclear → 0.0-0.6

Return ONLY valid JSON:
{"product_id": "<id or null>", "product_name": "<name or null>", "weight": "<weight or null>", "confidence": <0.0-1.0>, "candidates": []}
"""

ENTITY_USER_PROMPT = """Product mention: "{product_name}"
Weight hint: "{weight_hint}"

Match to catalog and return JSON."""


def _build_product_catalog() -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, product_name, weight FROM products WHERE is_active=1 ORDER BY product_name, weight"
        ).fetchall()
        conn.close()
        
        if not rows:
            logger.warning("[Entities] No products in database")
            return "No products loaded"
        
        lines = "\n".join(f"{r['id']} | {r['product_name']} | {r['weight']}" for r in rows)
        logger.info(f"[Entities] Loaded {len(rows)} products")
        return lines
    except Exception as e:
        logger.error(f"[Entities] Catalog load failed: {e}")
        return "Catalog load failed"


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
        raise ValueError(f"No JSON found: {text[:120]!r}")

    depth, in_str, escape = 0, False, False
    end = -1
    for i, ch in enumerate(clean[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end != -1:
        try:
            return json.loads(clean[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("[Entities] Truncated JSON, attempting repair")
    fragment = clean[start:]
    open_braces = fragment.count("{") - fragment.count("}")
    open_brackets = fragment.count("[") - fragment.count("]")
    repaired = fragment + ("]" * max(open_brackets, 0)) + ("}" * max(open_braces, 0))
    
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        raise ValueError(f"Unrecoverable JSON: {text[:200]!r}")


class EntityResolver:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.client = _client
        self._catalog = _build_product_catalog()

    def resolve(self, raw_entities: dict, retries: int = 3, backoff: float = 2.0) -> dict:
        product_name = (raw_entities.get("product_name") or "").strip()
        weight_hint = (raw_entities.get("weight_hint") or raw_entities.get("weight") or "").strip()

        if not product_name:
            logger.info("[Entities] No product name")
            return self._empty(raw_entities)

        for attempt in range(1, retries + 1):
            try:
                system = ENTITY_SYSTEM_PROMPT.format(product_catalog=self._catalog)
                user = ENTITY_USER_PROMPT.format(
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
                db_row = None
                
                if product_id:
                    db_row = self._fetch_product(product_id)

                resolved = {
                    "product_id": product_id,
                    "product_name": db_row.get("product_name") if db_row else result.get("product_name"),
                    "weight": db_row.get("weight") if db_row else result.get("weight"),
                    "mrp_unit": db_row.get("mrp_unit") if db_row else None,
                    "offer_rate": db_row.get("offer_rate_new") if db_row else None,
                    "retail": db_row.get("retail") if db_row else None,
                    "billing": db_row.get("billing") if db_row else None,
                    "tax_18_percent": db_row.get("tax_18_percent") if db_row else None,
                    "tax_12_percent": db_row.get("tax_12_percent") if db_row else None,
                    "candidates": result.get("candidates", []),
                    "confidence": result.get("confidence", 0.0),
                    "quantity": raw_entities.get("quantity"),
                    "order_ref": raw_entities.get("order_ref"),
                }

                logger.info(
                    f"[Entities] product_id={resolved['product_id']} "
                    f"name='{resolved['product_name']}' weight='{resolved['weight']}' "
                    f"mrp={resolved['mrp_unit']} retail={resolved['retail']} "
                    f"confidence={resolved['confidence']:.2f}"
                )
                return resolved

            except ServerError as e:
                if attempt < retries:
                    wait = backoff * attempt
                    logger.warning(f"[Entities] Gemini 503 — retry {attempt}/{retries}")
                    time.sleep(wait)
                else:
                    logger.error(f"[Entities] Gemini failed after {retries} attempts")
                    return self._empty(raw_entities)

            except Exception as e:
                logger.error(f"[Entities] {type(e).__name__}: {e}")
                return self._empty(raw_entities)

        return self._empty(raw_entities)

    def _fetch_product(self, product_id: str) -> dict:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM products WHERE id=? AND is_active=1", (product_id,)
            ).fetchone()
            conn.close()
            return dict(row) if row else {}
        except Exception as e:
            logger.error(f"[Entities] DB fetch failed for {product_id}: {e}")
            return {}

    def _empty(self, raw: dict = None) -> dict:
        return {
            "product_id": None,
            "product_name": None,
            "weight": None,
            "mrp_unit": None,
            "offer_rate": None,
            "retail": None,
            "billing": None,
            "tax_18_percent": None,
            "tax_12_percent": None,
            "candidates": [],
            "confidence": 0.0,
            "quantity": raw.get("quantity") if raw else None,
            "order_ref": raw.get("order_ref") if raw else None,
        }