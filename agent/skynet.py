"""
agent/skynet.py  — production-ready version
Fixes vs original:
  1. _lookup_caller: queries customer_type + area (now exist after call_patch.sql)
  2. new_session: injects cross-call caller_summary into every prompt
  3. _generate_response: uses response cache (saves ~300ms on repeated price/stock queries)
  4. run_turn: VAD-trimmed audio before STT
  5. on_call_end: transcript export + order extraction + caller summary update
  6. _summarise_caller: LLM CRM note persisted per phone number
  7. Memory tracking: intent_history + agent_turns for full transcript reconstruction
"""

import logging
import re
import time
import json
import sqlite3
import os
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

from stt.transcriber import Transcriber
from nlu.intent import IntentClassifier, get_response_cache
from nlu.entities import EntityResolver
from tts.synthesizer import TTSPipeline
from agent.prompt import (
    SYSTEM_PROMPT, SYSTEM_PROMPT_D2C, SYSTEM_PROMPT_RETAILER,
    SYSTEM_PROMPT_DISTRIBUTOR, SYSTEM_PROMPT_SUPER, RESPONSE_TEMPLATE,
    PRODUCT_KNOWLEDGE,
)
from agent.order import OrderExtractor
from agent.excel  import ExcelExporter

from google import genai
from google.genai import types

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SUMMARY_SYSTEM = """You are a CRM assistant for AryanVeda / Nimson sales.
Summarise this sales call in 3-4 sentences covering:
- Products discussed and what the caller wanted
- Whether an order was placed (and what)
- Caller's preferred language and tone
- Any follow-up needed
Write in English. Be concise and factual."""


# ── ConversationMemory ────────────────────────────────────────────────────────

ORDER_REQUIRED_FIELDS = ["quantity", "caller_name", "delivery_phone", "delivery_address", "pincode"]


class ConversationMemory:
    def __init__(self, session_id: str):
        self.session_id       = session_id
        self.turn             = 0
        self.history:         List[Dict] = []
        self.current_product: Optional[str] = None
        self.current_weight:  Optional[str] = None
        self.current_product_id: Optional[str] = None
        self.caller_history:  List[Dict] = []
        self.customer_type:   Optional[str] = None   # "retailer"|"distributor"|"super"|"d2c"
        self.intent_history:  List[str]  = []         # all intents seen this call
        self.agent_turns:     Dict[int, str] = {}     # turn_num → agent response text
        self.order_fields: Dict[str, Optional[str]] = {
            "quantity":         None,
            "caller_name":      None,
            "delivery_phone":   None,
            "delivery_address": None,
            "pincode":          None,
        }
        self.order_excel_saved: bool = False

    def order_state_str(self) -> str:
        product = (self.current_product or "--")
        weight  = (self.current_weight  or "--")
        lines   = [f"  product          : {product} {weight}".rstrip()]
        for key in ORDER_REQUIRED_FIELDS:
            val = self.order_fields.get(key) or "--"
            lines.append(f"  {key:<18}: {val}")
        return "\n".join(lines)

    def order_is_complete(self) -> bool:
        return (bool(self.current_product) and
                all(self.order_fields.get(f) for f in ORDER_REQUIRED_FIELDS))

    def update(self, transcript: str, intent: str, entity: dict,
               customer_type: Optional[str] = None):
        self.turn += 1
        if entity.get("product_name"):
            self.current_product = entity["product_name"]
        if entity.get("weight"):
            self.current_weight = entity["weight"]
        if entity.get("product_id"):
            self.current_product_id = entity["product_id"]
        if customer_type:
            self.customer_type = customer_type
        self.intent_history.append(intent)
        self.history.append({
            "turn":       self.turn,
            "text":       transcript,
            "intent":     intent,
            "product":    self.current_product,
            "product_id": self.current_product_id,
            "weight":     self.current_weight,
        })

    def context(self) -> dict:
        return {
            "history":         self.history,
            "current_product": self.current_product,
            "current_weight":  self.current_weight,
            "customer_type":   self.customer_type,
        }

    def full_transcript(self) -> List[Dict]:
        """Reconstruct interleaved caller+agent turns for transcript/order extraction."""
        turns = []
        for h in self.history:
            turns.append({"role": "caller", "turn": h["turn"] * 2 - 1, "text": h["text"]})
            agent_text = self.agent_turns.get(h["turn"], "")
            if agent_text:
                turns.append({"role": "agent", "turn": h["turn"] * 2, "text": agent_text})
        return sorted(turns, key=lambda x: x["turn"])


# ── Skynet ────────────────────────────────────────────────────────────────────

class Skynet:
    def __init__(self):
        logger.info("[Agent] Initializing Skynet...")
        self.transcriber       = Transcriber()
        self.intent_classifier = IntentClassifier()
        self.entity_resolver   = EntityResolver()
        self.tts               = TTSPipeline()
        self.order_extractor   = OrderExtractor()
        self.excel_exporter    = ExcelExporter()
        self._client           = _client
        self._cache            = get_response_cache()

        # VAD — optional, degrades gracefully
        try:
            from stt.vad import VAD
            self.vad = VAD()
        except Exception:
            self.vad = None
            logger.info("[Agent] VAD not available — running without silence trimming")

        DB_PATH   = os.getenv("DB_PATH", "db/aryanveda.db")
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        logger.info(f"[DB] Connected to {DB_PATH}")
        logger.info("[Agent] Skynet ready.")

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _db_fetch(self, query_text: str) -> List[Dict]:
        if not query_text:
            return []
        try:
            rows = self.conn.execute(
                "SELECT p.id, p.product_name, p.weight, "
                "p.mrp_unit, p.offer_rate_new, p.scheme_percentage, "
                "p.super_total, p.distributor_total, p.retail, "
                "COALESCE(i.closing_stock, -1) AS closing_stock "
                "FROM products p "
                "LEFT JOIN inventory i ON i.product_id = p.id "
                "WHERE LOWER(p.product_name) LIKE LOWER(?) AND p.is_active=1 LIMIT 20",
                (f"%{query_text}%",)
            ).fetchall()
            grouped: Dict[str, Dict] = {}
            for r in rows:
                p = r["product_name"]
                if p not in grouped:
                    grouped[p] = {"product_name": p, "variants": [], "pricing": []}
                if r["weight"]:
                    grouped[p]["variants"].append(r["weight"])
                grouped[p]["pricing"].append({
                    "weight":            r["weight"],
                    "mrp_unit":          r["mrp_unit"],
                    "offer_rate_new":    r["offer_rate_new"],
                    "scheme_percentage": r["scheme_percentage"],
                    "super_total":       r["super_total"],
                    "distributor_total": r["distributor_total"],
                    "retail":            r["retail"],
                    "closing_stock":     r["closing_stock"] if r["closing_stock"] >= 0 else None,
                })
            return list(grouped.values())[:5]
        except Exception as e:
            logger.warning(f"[DB] Fetch failed: {e}")
            return []

    def _build_conversation(self, history: List[Dict]) -> str:
        if not history:
            return "No prior turns."
        lines = []
        for h in history:
            lines.append(
                f"[Turn {h['turn']}] Caller: {h['text']} | "
                f"Intent: {h.get('intent','?')} | "
                f"Product: {h['product'] or 'none'} | Weight: {h['weight'] or 'none'}"
            )
        return "\n".join(lines)

    def _lookup_caller(self, phone: str) -> dict:
        calls_db = os.getenv("CALLS_DB_PATH", "db/call.db")
        try:
            conn = sqlite3.connect(calls_db)
            conn.row_factory = sqlite3.Row
            # customer_type and area exist after call_patch.sql
            row = conn.execute(
                "SELECT customer_type, name, area, preferred_language FROM callers WHERE phone_number=?",
                (phone,)
            ).fetchone()
            conn.close()
            if row:
                return dict(row)
        except Exception as e:
            logger.warning(f"[Session] Caller lookup failed: {e}")
        return {"customer_type": "unknown", "name": None, "area": None, "preferred_language": "hinglish"}

    def _select_prompt(self, customer_type: str) -> str:
        return {
            "retailer":    SYSTEM_PROMPT_RETAILER,
            "distributor": SYSTEM_PROMPT_DISTRIBUTOR,
            "super":       SYSTEM_PROMPT_SUPER,
            "d2c":         SYSTEM_PROMPT_D2C,
        }.get(customer_type or "", SYSTEM_PROMPT)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def new_session(self, session_id: str, db_session_id=None,
                    phone: str = "unknown", session_manager=None, **kwargs) -> dict:
        memory        = ConversationMemory(session_id)
        caller_info   = self._lookup_caller(phone) if phone and phone != "unknown" else {}
        customer_type = caller_info.get("customer_type", "unknown")
        memory.customer_type = customer_type if customer_type not in ("unknown", None) else None

        # Load last N sessions' snippet turns for prompt context
        if session_manager and phone and phone != "unknown":
            try:
                memory.caller_history = session_manager.get_caller_history(phone, n=3)
            except Exception as e:
                logger.warning(f"[Session] caller_history load failed: {e}")

        # Load cross-call LLM summary (injected into every prompt turn)
        caller_summary = ""
        if session_manager and phone and phone != "unknown":
            try:
                caller_summary = session_manager.get_caller_summary(phone) or ""
            except Exception as e:
                logger.warning(f"[Session] caller_summary load failed: {e}")

        self.intent_classifier.reset()
        self.entity_resolver.reset()

        return {
            "session_id":      session_id,
            "db_session_id":   db_session_id,
            "phone":           phone,
            "turn":            0,
            "memory":          memory,
            "session_manager": session_manager,
            "last_language":   caller_info.get("preferred_language", "hinglish"),
            "caller_info":     caller_info,
            "caller_summary":  caller_summary,
            "system_prompt":   self._select_prompt(customer_type),
        }

    # ── Turn execution ────────────────────────────────────────────────────────

    def run_turn(self, audio_bytes: bytes, session: dict) -> dict:
        t0 = time.time()

        # VAD silence trim (optional)
        if self.vad:
            try:
                audio_bytes = self.vad.strip_silence(audio_bytes)
            except Exception:
                pass

        result = self.transcriber.transcribe_stream(audio_bytes)
        text   = result["text"]
        conf   = result["confidence"]
        logger.info(f"[STT] '{text}' conf={conf:.2f}")

        out       = self._process_turn(text, session)
        full_text = out["response_text"]
        if out.get("followup_text"):
            full_text = full_text.rstrip() + " " + out["followup_text"]
        audio = self.tts.synthesizer.speak(full_text)

        out["audio_bytes"] = audio
        out["latency_ms"]  = int((time.time() - t0) * 1000)
        out["end_call"]    = out.get("intent") == "end_call"

        self.transcriber.set_context(out["response_text"])
        self._persist_turn(session, text, conf, out["response_text"],
                           out.get("followup_text", ""), out["intent"])
        return out

    def run_turn_text(self, text: str, session: dict) -> dict:
        t0  = time.time()
        out = self._process_turn(text, session)
        out["latency_ms"] = int((time.time() - t0) * 1000)
        return out

    def _process_turn(self, text: str, session: dict) -> dict:
        memory = session["memory"]
        session["turn"] += 1

        # Step 1: Intent + entity (single fast LLM call with flash-lite)
        intent_result = self.intent_classifier.classify(text)
        intent        = intent_result["intent"]
        language      = intent_result.get("language", "hinglish")
        session["last_language"] = language

        raw_product_hint = (intent_result["entities"].get("product_name") or
                            memory.current_product or text)

        # Step 2: Entity resolution + DB fetch in parallel
        with ThreadPoolExecutor(max_workers=2) as pool:
            entity_future = pool.submit(self.entity_resolver.resolve, intent_result["entities"])
            db_future     = pool.submit(self._db_fetch, raw_product_hint)
            entity_result = entity_future.result()
            db_data       = db_future.result()

        # Context carry-forward (caller refers back: "wahi wala", "same")
        if not entity_result.get("product_name"):
            entity_result["product_name"] = memory.current_product
        if not entity_result.get("weight"):
            entity_result["weight"] = memory.current_weight
        if not entity_result.get("product_id"):
            entity_result["product_id"] = memory.current_product_id

        product_name = entity_result.get("product_name")
        product_id   = entity_result.get("product_id")
        customer_type = memory.customer_type or session["caller_info"].get("customer_type")

        # Step 3: Check response cache (price/stock queries repeat constantly)
        cached = self._cache.get(intent, product_id, entity_result.get("weight"), customer_type)
        if cached:
            response = cached
        else:
            response = self._generate_response(
                transcript     = text,
                db_data        = db_data,
                entity         = entity_result,
                memory         = memory,
                language       = language,
                system_prompt  = session.get("system_prompt"),
                caller_summary = session.get("caller_summary", ""),
            )
            # Cache price/stock responses
            if intent in ("get_price", "check_stock") and product_id:
                self._cache.set(intent, product_id, entity_result.get("weight"),
                                customer_type, response)

        # Detect customer_type from transcript text directly (before LLM response)
        # This fires the moment caller says "retailer hu" / "distributor hoon" etc.
        if not memory.customer_type:
            tl = text.lower()
            if any(w in tl for w in ["retailer", "retail", "dukan", "shop owner", "shopkeeper"]):
                _detected = "retailer"
            elif any(w in tl for w in ["distributor", "distribution", "distrib"]):
                _detected = "distributor"
            elif any(w in tl for w in ["super stockist", "super stokkist", "stockist", "super stock"]):
                _detected = "super"
            elif any(w in tl for w in ["personal", "khud ke liye", "ghar ke liye", "apne liye", "consumer", "direct"]):
                _detected = "d2c"
            else:
                _detected = response.get("customer_type")  # fallback to LLM response
            if _detected and _detected not in ("unknown", None, ""):
                memory.customer_type = _detected
                session["system_prompt"] = self._select_prompt(_detected)
                logger.info(f"[Session] customer_type='{_detected}' detected from transcript")
                sm = session.get("session_manager")
                if sm and session.get("phone", "unknown") != "unknown":
                    try:
                        sm.update_caller_type(session["phone"], _detected)
                    except Exception:
                        pass

        memory.update(text, intent, entity_result, customer_type=None)
        # Track agent response for transcript reconstruction
        memory.agent_turns[memory.turn] = response.get("response", "")

        self.intent_classifier.add_agent_turn(response["response"])
        self.entity_resolver.share_history(memory.history)

        sm     = session.get("session_manager")
        db_sid = session.get("db_session_id")
        if sm and db_sid:
            try:
                sm.set_context(db_sid, "last_intent",   intent)
                sm.set_context(db_sid, "last_product",  product_name or "")
                sm.set_context(db_sid, "last_language", language)
            except Exception as e:
                logger.warning(f"[DB] context save failed: {e}")

        # ── Order field collection ──────────────────────────────────────────
        if intent in ("place_order", "confirm") and not memory.order_excel_saved:
            extracted = response.get("extracted") or {}
            for field in ORDER_REQUIRED_FIELDS:
                val = extracted.get(field)
                if val and not memory.order_fields.get(field):
                    memory.order_fields[field] = str(val)
            # Regex fallbacks on raw transcript
            if not memory.order_fields["pincode"]:
                m = re.search(r"\b([1-9]\d{5})\b", text)
                if m:
                    memory.order_fields["pincode"] = m.group(1)
            if not memory.order_fields["delivery_phone"]:
                m = re.search(r"\b([6-9]\d{9})\b", text)
                if m:
                    memory.order_fields["delivery_phone"] = m.group(1)
            if not memory.order_fields["quantity"] and entity_result.get("quantity"):
                memory.order_fields["quantity"] = str(entity_result["quantity"])
            # Save Excel the moment all fields are complete
            if memory.order_is_complete():
                try:
                    order_dict = {
                        "phone":            session.get("phone", ""),
                        "caller_name":      memory.order_fields.get("caller_name", ""),
                        "customer_type":    memory.customer_type or "",
                        "delivery_phone":   memory.order_fields.get("delivery_phone", ""),
                        "delivery_address": memory.order_fields.get("delivery_address", ""),
                        "pincode":          memory.order_fields.get("pincode", ""),
                        "notes":            "",
                        "items": [{
                            "product_name": memory.current_product or "",
                            "weight":       memory.current_weight  or "",
                            "quantity":     int(memory.order_fields.get("quantity") or 0),
                            "unit_price":   entity_result.get("retail") or entity_result.get("mrp_unit") or 0.0,
                            "total_price":  round(
                                int(memory.order_fields.get("quantity") or 0) *
                                float(entity_result.get("retail") or entity_result.get("mrp_unit") or 0),
                                2),
                        }],
                    }
                    db_sid = session.get("db_session_id") or session.get("session_id", "")
                    excel_path = self.excel_exporter.save(order_dict, session_id=db_sid) or ""
                    memory.order_excel_saved = True
                    logger.info(f"[Order] Excel saved -> {excel_path}")
                    sm = session.get("session_manager")
                    if sm and db_sid:
                        try:
                            sm.save_order(db_sid, order_dict, excel_path)
                        except Exception as db_err:
                            logger.warning(f"[Order] DB save failed: {db_err}")
                except Exception as e:
                    logger.error(f"[Order] Excel save failed: {e}")

        return {
            "transcript":    text,
            "intent":        intent,
            "entities":      entity_result,
            "response_text": response["response"],
            "followup_text": response.get("followup"),
        }

    # ── Response generation ───────────────────────────────────────────────────

    def _generate_response(self, transcript: str, db_data: list, entity: dict,
                           memory: ConversationMemory, language: str,
                           system_prompt: str = None, caller_summary: str = "") -> dict:
        from datetime import datetime, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        ctx = memory.context()

        # Format caller_history snippets for prompt injection
        history_text = ""
        if memory.caller_history:
            snippets = []
            for h in memory.caller_history[:2]:
                if h.get("last_turns"):
                    for t in h["last_turns"][-2:]:
                        snippets.append(f"  [{t['speaker']}]: {t['text']}")
            if snippets:
                history_text = "Recent previous call snippets:\n" + "\n".join(snippets)

        caller_ctx = "\n".join(filter(None, [caller_summary, history_text])) or "No prior history."

        prompt = RESPONSE_TEMPLATE.format(
            conversation_transcript = self._build_conversation(ctx["history"]),
            transcript              = transcript,
            db_data                 = json.dumps(db_data, ensure_ascii=False),
            current_state           = json.dumps({
                "product":         ctx["current_product"],
                "weight":          ctx["current_weight"],
                "customer_type":   ctx["customer_type"],
                "order_confirmed": memory.order_excel_saved,
            }),
            caller_history    = caller_ctx,
            order_state       = memory.order_state_str(),
            product_knowledge = PRODUCT_KNOWLEDGE,
            current_date      = now.strftime("%A, %d %B %Y"),
            current_time      = now.strftime("%I:%M %p IST"),
            caller_language   = language,
        )

        try:
            response = self._client.models.generate_content(
                model    = os.getenv("RESPONSE_MODEL", "gemini-2.5-flash"),
                contents = prompt,
                config   = types.GenerateContentConfig(
                    system_instruction = system_prompt or SYSTEM_PROMPT,
                    temperature        = 0.4,
                    max_output_tokens  = 350,
                    thinking_config    = types.ThinkingConfig(thinking_budget=0),
                    response_mime_type = "application/json",
                ),
            )
            raw = (getattr(response, "text", "") or "").strip()
            raw = raw.replace("₹", "rupaye ")

            start = raw.find("{")
            end   = raw.rfind("}")
            if start != -1 and end != -1:
                raw = raw[start:end + 1]

            try:
                result = json.loads(raw)
                logger.info(f"[Response] '{result.get('response','')[:80]}'")
                return result
            except json.JSONDecodeError:
                # Graceful extraction fallback
                def _extract(key, text):
                    idx = text.find(f'"{key}"')
                    if idx == -1: return None
                    after = text[idx + len(key) + 2:]
                    colon = after.find(":")
                    if colon == -1: return None
                    after = after[colon + 1:].strip().lstrip('"')
                    end_  = after.find('",')
                    if end_ == -1: end_ = after.rfind('"')
                    return after[:end_].strip() if end_ != -1 else after.strip()
                r = _extract("response", raw)
                f = _extract("followup", raw)
                if r:
                    return {"response": r, "followup": f}
                return self._fallback(entity)

        except Exception as e:
            logger.error(f"[LLM] Failed: {e}")
            return self._fallback(entity)

    # ── Call end pipeline ─────────────────────────────────────────────────────

    def on_call_end(self, session: dict):
        """
        Call from server.py finally block.
        Exports transcript → extracts order → writes Excel → updates caller summary.
        """
        sm          = session.get("session_manager")
        db_sid      = session.get("db_session_id")
        memory      = session.get("memory")
        phone       = session.get("phone", "unknown")
        caller_info = session.get("caller_info", {})

        if not sm or not db_sid or not memory:
            return

        # 1. Export transcript
        try:
            path = sm.export_transcript(db_sid)
            if path:
                logger.info(f"[CallEnd] Transcript → {path}")
        except Exception as e:
            logger.warning(f"[CallEnd] Transcript failed: {e}")

        # 2. Order extraction (only if place_order intent seen)
        if self.order_extractor.has_order_intent(memory.intent_history):
            try:
                turns = memory.full_transcript()
                order = self.order_extractor.extract(
                    transcript_turns = turns,
                    phone            = phone,
                    caller_name      = caller_info.get("name", ""),
                    customer_type    = memory.customer_type or caller_info.get("customer_type", ""),
                )
                if order:
                    excel_path = self.excel_exporter.save(order, session_id=db_sid) or ""
                    sm.save_order(db_sid, order, excel_path)
                    logger.info(f"[CallEnd] Order saved → {excel_path}")
            except Exception as e:
                logger.error(f"[CallEnd] Order extraction failed: {e}")

        # 3. Caller summary update
        try:
            self._summarise_caller(memory, phone, sm)
        except Exception as e:
            logger.warning(f"[CallEnd] Summary failed: {e}")

    def _summarise_caller(self, memory: ConversationMemory, phone: str, sm):
        if len(memory.history) < 2:
            return
        existing = sm.get_caller_summary(phone) or ""
        convo    = self._build_conversation(memory.history)
        products = list({h["product"] for h in memory.history if h.get("product")})
        last_intent = memory.intent_history[-1] if memory.intent_history else ""

        prompt = f"""Previous summary (update/extend this):
{existing}

Latest call:
{convo}

Write a fresh 3-4 sentence CRM summary of this caller for the sales team."""

        try:
            resp = self._client.models.generate_content(
                model    = "gemini-2.5-flash",
                contents = prompt,
                config   = types.GenerateContentConfig(
                    system_instruction = SUMMARY_SYSTEM,
                    temperature        = 0.2,
                    max_output_tokens  = 200,
                ),
            )
            summary = (getattr(resp, "text", "") or "").strip()
            if summary:
                sm.save_caller_summary(
                    phone        = phone,
                    summary      = summary,
                    last_products = json.dumps(products),
                    last_intent  = last_intent,
                )
                logger.info(f"[CallEnd] CRM summary updated for {phone}")
        except Exception as e:
            logger.warning(f"[CallEnd] Summary LLM call failed: {e}")

    # ── DB turn persistence ───────────────────────────────────────────────────

    def _persist_turn(self, session: dict, transcript: str, confidence: float,
                      response: str, followup: str, intent: str):
        sm     = session.get("session_manager")
        db_sid = session.get("db_session_id")
        if not sm or not db_sid:
            return
        idx = session["turn"] - 1
        try:
            sm.save_turn(db_sid, idx,     "caller", transcript, confidence)
            sm.save_turn(db_sid, idx + 1, "agent",
                         response + (" " + followup if followup else ""))
            sm.set_context(db_sid, "last_intent", intent)
        except Exception as e:
            logger.warning(f"[DB] turn persist failed: {e}")

    def _fallback(self, entity: dict) -> dict:
        p = entity.get("product_name") or ""
        return {
            "response": (f"Haan sir, {p} ke baare mein batata hoon.".strip() if p
                         else "Haan sir, batao — main kya madad kar sakta hoon?"),
            "followup": "Kaunsa product ya size dekhna tha aapko?",
        }