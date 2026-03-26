import logging
import time
import json
import sqlite3
import os
from typing import List, Dict, Optional

from stt.transcriber import Transcriber
from nlu.intent import IntentClassifier
from nlu.entities import EntityResolver
from tts.synthesizer import TTSPipeline
from agent.prompt import SYSTEM_PROMPT, RESPONSE_TEMPLATE

from google import genai
from google.genai import types

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


class ConversationMemory:
    def __init__(self, session_id: str):
        self.session_id      = session_id
        self.turn            = 0
        self.history:        List[Dict] = []
        self.current_product: Optional[str] = None
        self.current_weight:  Optional[str] = None
        self.caller_history:  List[Dict] = []
        self.customer_type:   Optional[str] = None  # "retailer" | "distributor" | "super"

    def update(self, transcript: str, intent: str, entity: dict, customer_type: Optional[str] = None):
        self.turn += 1
        if entity.get("product_name"):
            self.current_product = entity["product_name"]
        if entity.get("weight"):
            self.current_weight = entity["weight"]
        if customer_type:
            self.customer_type = customer_type
        self.history.append({
            "turn":    self.turn,
            "text":    transcript,
            "intent":  intent,
            "product": self.current_product,
            "weight":  self.current_weight,
        })

    def context(self) -> dict:
        return {
            "history":         self.history,
            "current_product": self.current_product,
            "current_weight":  self.current_weight,
            "customer_type":   self.customer_type,
        }


class Skynet:
    def __init__(self):
        logger.info("[Agent] Initializing Skynet...")
        self.transcriber       = Transcriber()
        self.intent_classifier = IntentClassifier()
        self.entity_resolver   = EntityResolver()
        self.tts               = TTSPipeline()
        self._client           = _client

        DB_PATH   = os.getenv("DB_PATH", "db/aryanveda.db")
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        logger.info(f"[DB] Connected to {DB_PATH}")
        logger.info("[Agent] Skynet ready.")

    def _db_fetch(self, query_text: str) -> List[Dict]:
        try:
            rows = self.conn.execute(
                "SELECT p.id, p.product_name, p.weight, "
                "p.mrp_unit, p.super_total, p.distributor_total, p.retail, "
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
                f"[Turn {h['turn']}] User: {h['text']} | "
                f"Product: {h['product'] or 'none'} | Weight: {h['weight'] or 'none'}"
            )
        return "\n".join(lines)

    def new_session(self, session_id: str, db_session_id=None,
                    phone: str = "unknown", session_manager=None, **kwargs) -> dict:
        memory = ConversationMemory(session_id)
        if session_manager and phone and phone != "unknown":
            try:
                memory.caller_history = session_manager.get_caller_history(phone, n=3)
            except Exception as e:
                logger.warning(f"[Session] Could not load caller history: {e}")
        self.intent_classifier.reset()
        self.entity_resolver.reset()
        return {
            "session_id":      session_id,
            "db_session_id":   db_session_id,
            "phone":           phone,
            "turn":            0,
            "memory":          memory,
            "session_manager": session_manager,
            "last_language":   "hinglish",
        }

    def run_turn(self, audio_bytes: bytes, session: dict) -> dict:
        t0     = time.time()
        result = self.transcriber.transcribe_stream(audio_bytes)
        text   = result["text"]
        conf   = result["confidence"]
        logger.info(f"[STT] '{text}' conf={conf:.2f}")

        out   = self._process_turn(text, session)
        # Merge response and followup into one TTS call — halves ElevenLabs round trips
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
        from concurrent.futures import ThreadPoolExecutor
        memory = session["memory"]
        session["turn"] += 1

        # Step 1: NLU — must be first, everything depends on it
        intent_result = self.intent_classifier.classify(text)
        intent        = intent_result["intent"]
        language      = intent_result.get("language", "hinglish")
        session["last_language"] = language

        # Step 2: Entity resolve + DB fetch in parallel
        # DB fetch only needs the raw product hint from NLU, not the resolved entity
        raw_product_hint = (intent_result["entities"].get("product_name") or
                           memory.current_product or text)

        with ThreadPoolExecutor(max_workers=2) as pool:
            entity_future = pool.submit(self.entity_resolver.resolve, intent_result["entities"])
            db_future     = pool.submit(self._db_fetch, raw_product_hint)
            entity_result = entity_future.result()
            db_data       = db_future.result()

        # Context recovery — carry forward if caller used a reference
        if not entity_result.get("product_name"):
            entity_result["product_name"] = memory.current_product
        if not entity_result.get("weight"):
            entity_result["weight"] = memory.current_weight

        product_name = entity_result.get("product_name")

        response = self._generate_response(
            transcript    = text,
            db_data       = db_data,
            entity        = entity_result,
            memory        = memory,
            language      = language,
        )

        customer_type = response.get("customer_type") or memory.customer_type
        memory.update(text, intent, entity_result, customer_type=customer_type)
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

        return {
            "transcript":    text,
            "intent":        intent,
            "entities":      entity_result,
            "response_text": response["response"],
            "followup_text": response.get("followup"),
        }

    def _generate_response(self, transcript: str, db_data: list,
                           entity: dict, memory: ConversationMemory, language: str) -> dict:
        from datetime import datetime, timezone, timedelta
        IST     = timezone(timedelta(hours=5, minutes=30))
        now     = datetime.now(IST)
        context = memory.context()

        prompt = RESPONSE_TEMPLATE.format(
            conversation_transcript = self._build_conversation(context["history"]),
            transcript              = transcript,
            db_data                 = json.dumps(db_data, ensure_ascii=False),
            current_state           = json.dumps({
                "product":       context["current_product"],
                "weight":        context["current_weight"],
                "customer_type": context["customer_type"],
            }),
            current_date    = now.strftime("%A, %d %B %Y"),
            current_time    = now.strftime("%I:%M %p IST"),
            caller_language = language,
        )

        try:
            response = self._client.models.generate_content(
                model    = "gemini-2.5-flash",
                contents = prompt,
                config   = types.GenerateContentConfig(
                    system_instruction = SYSTEM_PROMPT,
                    temperature        = 0.4,
                    max_output_tokens  = 400,
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
                def _extract(key, text):
                    idx = text.find(f'"{key}"')
                    if idx == -1:
                        return None
                    after = text[idx + len(key) + 2:]
                    colon = after.find(":")
                    if colon == -1:
                        return None
                    after = after[colon + 1:].strip().lstrip('"')
                    end   = after.find('",')
                    if end == -1:
                        end = after.rfind('"')
                    return after[:end].strip() if end != -1 else after.strip()
                r = _extract("response", raw)
                f = _extract("followup", raw)
                if r:
                    return {"response": r, "followup": f}
                return self._fallback(entity)

        except Exception as e:
            logger.error(f"[LLM] Failed: {e}")
            return self._fallback(entity)

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
            "response": f"Haan sir, {p} ke baare mein batata hoon.".strip() if p
                        else "Haan sir, batao — main kya madad kar sakta hoon?",
            "followup": "Kaunsa product ya size dekhna tha aapko?",
        }