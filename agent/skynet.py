import os
import json
import uuid
import logging
import sqlite3
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

from stt.transcriber import Transcriber
from tts.synthesizer import TTSPipeline
from nlu.intent import IntentClassifier
from nlu.entities import EntityResolver

load_dotenv()
logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")

_PERSONA = """You are Tanmay, AryanVeda's friendly Hinglish sales assistant on a phone call.
- Natural Hinglish — the way Indian salespeople actually talk
- Warm, like a trusted business friend — "bhai", "ji", "yaar" naturally
- 2-3 sentences MAX — this is voice, not chat
- Never mention SKU codes, batch numbers, or internal IDs
- Be proactive: mention low stock as urgency, suggest alternatives if out of stock
- Remember everything said earlier in this call
- If multiple sizes asked, list all of them with stock and price"""


# ── DB helpers ────────────────────────────────────────────────────────────────

def _fetch_by_sku(sku_code: str, distributor_code: str = None) -> list:
    """Exact SKU lookup with optional distributor filter."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if distributor_code:
            rows = conn.execute("""
                SELECT s.name AS product, s.category, s.unit,
                       s.base_price AS dealer_price, s.mrp,
                       ds.stock_qty, d.name AS distributor, d.city
                FROM skus s
                JOIN distributor_skus ds ON ds.sku_id = s.id
                JOIN distributors d      ON d.id = ds.distributor_id
                WHERE s.sku_code = ? AND d.code = ? AND s.is_active = 1
            """, (sku_code, distributor_code)).fetchall()
        else:
            rows = conn.execute("""
                SELECT s.name AS product, s.category, s.unit,
                       s.base_price AS dealer_price, s.mrp,
                       SUM(ds.stock_qty) AS stock_qty,
                       GROUP_CONCAT(d.city) AS cities
                FROM skus s
                JOIN distributor_skus ds ON ds.sku_id = s.id
                JOIN distributors d      ON d.id = ds.distributor_id
                WHERE s.sku_code = ? AND s.is_active = 1
                GROUP BY s.id
            """, (sku_code,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _search_by_name(product_name: str, distributor_code: str = None) -> list:
    """
    Fuzzy name search — splits product_name into words and does LIKE matching.
    Returns ALL matching variants (e.g. all almond oil sizes) ranked by stock.
    """
    words = [w for w in product_name.lower().split() if len(w) > 2]
    if not words:
        return []

    conn   = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    clause = " AND ".join(f"LOWER(s.name) LIKE ?" for _ in words)
    params = [f"%{w}%" for w in words]

    try:
        if distributor_code:
            params.append(distributor_code)
            rows = conn.execute(f"""
                SELECT s.sku_code, s.name AS product, s.category, s.unit,
                       s.base_price AS dealer_price, s.mrp,
                       ds.stock_qty, d.name AS distributor, d.city
                FROM skus s
                JOIN distributor_skus ds ON ds.sku_id = s.id
                JOIN distributors d      ON d.id = ds.distributor_id
                WHERE {clause} AND d.code = ? AND s.is_active = 1
                ORDER BY ds.stock_qty DESC
            """, params).fetchall()
        else:
            rows = conn.execute(f"""
                SELECT s.sku_code, s.name AS product, s.category, s.unit,
                       s.base_price AS dealer_price, s.mrp,
                       SUM(ds.stock_qty) AS stock_qty
                FROM skus s
                JOIN distributor_skus ds ON ds.sku_id = s.id
                WHERE {clause} AND s.is_active = 1
                GROUP BY s.id ORDER BY stock_qty DESC
            """, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _list_available(distributor_code: str) -> list:
    """All products with stock > 0 at a distributor."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT s.name AS product, s.category,
                   s.base_price AS dealer_price, s.mrp, ds.stock_qty
            FROM skus s
            JOIN distributor_skus ds ON ds.sku_id = s.id
            JOIN distributors d      ON d.id = ds.distributor_id
            WHERE d.code = ? AND ds.stock_qty > 0 AND s.is_active = 1
            ORDER BY ds.stock_qty DESC LIMIT 12
        """, (distributor_code,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _place_order(sku_code: str, distributor_code: str,
                 quantity: int, session_id: str) -> dict:
    """
    Place order using flat orders table — matches actual schema.
    Schema: orders(id, order_ref, session_id, distributor_id, sku_id,
                   quantity, unit_price, total_amount, status, ...)
    NO order_items table exists.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        sku  = conn.execute(
            "SELECT id, name, base_price, unit FROM skus WHERE sku_code=? AND is_active=1",
            (sku_code,)).fetchone()
        dist = conn.execute(
            "SELECT id, name FROM distributors WHERE code=? AND is_active=1",
            (distributor_code,)).fetchone()
        if not sku or not dist:
            logger.error(f"[DB] place_order: sku={sku_code} or dist={distributor_code} not found")
            return {}

        order_ref = "ORD-" + str(uuid.uuid4())[:8].upper()
        total     = round(sku["base_price"] * quantity, 2)

        conn.execute("""
            INSERT INTO orders
              (id, order_ref, session_id, distributor_id, sku_id,
               quantity, unit_price, total_amount, status)
            VALUES (?,?,?,?,?,?,?,?,'confirmed')
        """, (str(uuid.uuid4()), order_ref, session_id,
              dist["id"], sku["id"],
              quantity, sku["base_price"], total))
        conn.commit()

        return {
            "order_ref":   order_ref,
            "product":     sku["name"],
            "distributor": dist["name"],
            "quantity":    quantity,
            "unit":        sku["unit"],
            "total":       total,
        }
    except Exception as e:
        logger.error(f"[DB] place_order failed: {e}")
        return {}
    finally:
        conn.close()


# ── Main agent ────────────────────────────────────────────────────────────────

class Skynet:
    def __init__(self):
        logger.info("Initializing Skynet...")
        self.stt    = Transcriber()
        self.tts    = TTSPipeline()
        self.nlu    = IntentClassifier()
        self.ner    = EntityResolver()
        self.client = _client
        self.model  = "gemini-2.5-flash"
        logger.info("Skynet ready.")

    def run_turn(self, audio_bytes: bytes, session: dict) -> dict:
        t0 = time.time()

        stt_result = self.stt.transcribe(audio_bytes)
        transcript = stt_result["text"]

        nlu_result = self.nlu.classify(transcript)
        intent     = nlu_result["intent"]
        entities   = self.ner.resolve(nlu_result["entities"])
        entities   = self._fill_from_session(entities, session)

        response_text = self._converse(transcript, intent, entities, session)
        audio_out     = self.tts.synthesizer.speak(response_text)
        self._update_session(session, intent, entities)

        return {
            "transcript":    transcript,
            "intent":        intent,
            "action":        intent,
            "entities":      entities,
            "sku_data":      {},
            "response_text": response_text,
            "audio_bytes":   audio_out,
            "latency_ms":    int((time.time() - t0) * 1000),
            "end_call":      intent == "end_call",
        }

    def _converse(self, transcript: str, intent: str,
                  entities: dict, session: dict) -> str:

        sku_code  = entities.get("sku_code")
        dist_code = entities.get("distributor_code")
        prod_name = entities.get("product_name") or ""
        dist_name = entities.get("distributor_name") or session.get("last_distributor_name", "")
        quantity  = entities.get("quantity")

        # ── DB fetch — three strategies in priority order ─────────────────────
        db_block = ""
        rows     = []

        if intent in ("check_stock", "get_price", "list_skus"):
            rows = []

            # Strategy 1: exact SKU lookup — single row, precise
            if sku_code:
                rows = _fetch_by_sku(sku_code, dist_code)

            # Strategy 2: ALWAYS run name search when prod_name exists —
            # catches all variants (100ml, 200ml, 500ml) that SKU lookup misses.
            # Merge results, deduplicate by sku_code so no row appears twice.
            if prod_name:
                name_rows   = _search_by_name(prod_name, dist_code)
                existing    = {r.get("sku_code") for r in rows}
                rows       += [r for r in name_rows if r.get("sku_code") not in existing]

            # Strategy 3: fallback — list everything at distributor
            if not rows and dist_code:
                rows = _list_available(dist_code)

            if rows:
                loc_header = f" at {dist_name}" if dist_name else ""
                db_block   = f"STOCK & PRICE DATA{loc_header}:\n"
                for r in rows:
                    loc = r.get("city") or r.get("cities") or r.get("distributor", "")
                    db_block += (
                        f"• {r['product']} | "
                        f"Stock: {r['stock_qty']} {r.get('unit','pcs')} | "
                        f"Dealer: ₹{r['dealer_price']} | MRP: ₹{r['mrp']}"
                        + (f" | {loc}" if loc and not dist_code else "") + "\n"
                    )
            else:
                db_block = (
                    f"No data found for '{prod_name or sku_code}'"
                    + (f" at {dist_name}" if dist_name else "") + "."
                )

        elif intent == "place_order":
            if session.get("pending_order"):
                p      = session["pending_order"]
                result = _place_order(p["sku_code"], p["dist_code"],
                                      p["qty"], session.get("session_id", "test"))
                db_block = f"ORDER PLACED: {json.dumps(result)}" if result else "Order failed."
                session["pending_order"] = None
            elif sku_code and dist_code and quantity:
                rows = _fetch_by_sku(sku_code, dist_code)
                if rows:
                    db_block = f"ORDER PREVIEW (confirm with customer):\n• {rows[0]}\nQty: {quantity}"
                    session["pending_order"] = {
                        "sku_code": sku_code, "dist_code": dist_code, "qty": quantity
                    }
                else:
                    db_block = "Product not found for this distributor."
            else:
                missing = [f for f, v in [
                    ("product", sku_code), ("location", dist_code), ("quantity", quantity)
                ] if not v]
                db_block = f"Still need to place order: {', '.join(missing)}"

        elif intent == "confirm" and session.get("pending_order"):
            p      = session["pending_order"]
            result = _place_order(p["sku_code"], p["dist_code"],
                                  p["qty"], session.get("session_id", "test"))
            db_block = f"ORDER CONFIRMED: {json.dumps(result)}" if result else "Order failed."
            session["pending_order"] = None

        # ── Conversation history ──────────────────────────────────────────────
        history   = session.get("history", [])
        hist_text = "".join(
            f"Customer: {t['user']}\nTanmay: {t['agent']}\n\n"
            for t in history[-6:]
        )

        # ── Generate response ─────────────────────────────────────────────────
        prompt = f"""=== CALL HISTORY ===
{hist_text or "(start of call)"}
=== CURRENT INPUT ===
Customer: "{transcript}"
Intent: {intent}
Product resolved: {prod_name} (code: {sku_code or 'not resolved'})
Location: {dist_name or dist_code or 'not specified'}
Quantity: {quantity or 'not specified'}

=== DATABASE RESULTS ===
{db_block or 'No DB query needed.'}

=== INSTRUCTION ===
Respond as Tanmay. Natural Hinglish, 2-3 sentences, no SKU codes.
Use DB results to give accurate info. If multiple products found, list key ones.
If product not resolved, ask naturally — do not be robotic."""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_PERSONA,
                    temperature=0.4,
                    max_output_tokens=600,
                ),
            )
            text = response.text.strip()
        except Exception as e:
            logger.error(f"[Skynet] converse failed: {e}")
            text = "Ek second bhai, kuch technical issue aa gaya. Dobara bolo please."

        history.append({"user": transcript, "agent": text})
        session["history"] = history[-12:]
        logger.info(f"[Skynet] → {text}")
        return text

    def _fill_from_session(self, entities: dict, session: dict) -> dict:
        for key, skey in [
            ("sku_code",         "last_sku"),
            ("distributor_code", "last_distributor"),
            ("product_name",     "last_product_name"),
            ("distributor_name", "last_distributor_name"),
        ]:
            if not entities.get(key) and session.get(skey):
                entities[key] = session[skey]
        return entities

    def _update_session(self, session: dict, intent: str, entities: dict):
        if entities.get("sku_code"):
            session["last_sku"] = entities["sku_code"]
        if entities.get("distributor_code"):
            session["last_distributor"] = entities["distributor_code"]
        if entities.get("product_name"):
            session["last_product_name"] = entities["product_name"]
        if entities.get("distributor_name"):
            session["last_distributor_name"] = entities["distributor_name"]
        session["turn"] = session.get("turn", 0) + 1