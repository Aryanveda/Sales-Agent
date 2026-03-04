import os
import re
import json
import logging
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

from stt.transcriber import Transcriber
from tts.synthesizer import TTSPipeline
from nlu.intent import IntentClassifier
from nlu.entities import EntityResolver
from sku.lookup import SKULookup
from agent.prompt import SKYNET_SYSTEM_PROMPT, SKYNET_USER_PROMPT

load_dotenv()
logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _parse_json(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("Empty response from model")
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned.strip())


def _extract_text(response) -> str:
    raw = response.text if response.text else ""
    if not raw and response.candidates:
        raw = "".join(
            part.text
            for part in response.candidates[0].content.parts
            if hasattr(part, "text") and part.text
        )
    return raw


class Skynet:
    def __init__(self):
        logger.info("Initializing Skynet...")
        self.stt    = Transcriber()
        self.tts    = TTSPipeline()
        self.nlu    = IntentClassifier()
        self.ner    = EntityResolver()
        self.sku    = SKULookup()
        self.client = _client
        self.model  = "gemini-2.5-flash"
        logger.info("Skynet ready.")

    def run_turn(self, audio_bytes: bytes, session: dict) -> dict:
        t0 = time.time()

        # ── 1. STT ───────────────────────────────────────────────────────────
        stt_result = self.stt.transcribe(audio_bytes)
        transcript = stt_result["text"]
        confidence = stt_result["confidence"]

        # ── 2. Intent + Entities ─────────────────────────────────────────────
        nlu_result = self.nlu.classify(transcript)
        intent     = nlu_result["intent"]
        entities   = self.ner.resolve(nlu_result["entities"])

        # Fill gaps from session memory
        entities = self._fill_from_session(entities, session)

        # ── 3. Skynet Decision ───────────────────────────────────────────────
        sku_data = {}
        decision = self._decide(intent, entities, session, sku_data, confidence)
        action   = decision["action"]
        logger.info(f"[Skynet] action={action} | reason={decision.get('reasoning')}")

        # ── 4. Execute action ────────────────────────────────────────────────
        sku_data = self._execute(action, entities, session)

        # ── 5. If sku_data came back, re-decide with full picture ────────────
        if sku_data:
            decision = self._decide(intent, entities, session, sku_data, confidence)
            action   = decision["action"]

        # ── 6. TTS response ──────────────────────────────────────────────────
        response_text, audio_out = self.tts.respond(action, sku_data, entities)

        # ── 7. Update session ────────────────────────────────────────────────
        self._update_session(session, intent, action, entities, sku_data)

        return {
            "transcript":    transcript,
            "intent":        intent,
            "action":        action,
            "entities":      entities,
            "sku_data":      sku_data,
            "response_text": response_text,
            "audio_bytes":   audio_out,
            "latency_ms":    int((time.time() - t0) * 1000),
            "end_call":      action in ["respond_direct"] and intent in ["end_call", "escalate"],
        }

    # ── Gemini Decision Engine ────────────────────────────────────────────────

    def _decide(self, intent: str, entities: dict, session: dict, sku_data: dict, confidence: float) -> dict:
        try:
            prompt = SKYNET_USER_PROMPT.format(
                intent=intent,
                entities=json.dumps(entities, ensure_ascii=False),
                session=json.dumps({
                    "last_sku":         session.get("last_sku"),
                    "last_distributor": session.get("last_distributor"),
                    "pending_order":    session.get("pending_order"),
                    "turn":             session.get("turn"),
                    "stt_confidence":   confidence,
                }, ensure_ascii=False),
                sku_data=json.dumps(sku_data, ensure_ascii=False, default=str),
            )
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SKYNET_SYSTEM_PROMPT,
                    temperature=0,
                    max_output_tokens=150,
                    response_mime_type="application/json",
                ),
            )
            return _parse_json(_extract_text(response))

        except Exception as e:
            logger.error(f"[Skynet] decision failed: {e}")
            return {"action": "retry_unclear", "reasoning": "decision engine error"}

    # ── Action Executor ───────────────────────────────────────────────────────

    def _execute(self, action: str, entities: dict, session: dict) -> dict:
        sku  = entities.get("sku_code")
        dist = entities.get("distributor_code")
        qty  = entities.get("quantity")

        try:
            if action == "fetch_stock":
                return self.sku.check_stock(sku, dist) or {}

            elif action == "fetch_price":
                return self.sku.get_price(sku, dist) or {}

            elif action == "fetch_sku_list":
                return self.sku.list_skus(dist)

            elif action == "request_confirm":
                return self.sku.get_price(sku, dist) or {}

            elif action == "place_order":
                pending = session.get("pending_order", {})
                return self.sku.place_order(
                    sku_code=pending.get("sku_code", sku),
                    distributor_code=pending.get("distributor_code", dist),
                    quantity=pending.get("quantity", qty),
                    session_id=session.get("session_id"),
                ) or {}

            elif action == "fetch_order_status":
                ref = entities.get("order_ref")
                return self.sku.get_order_status(ref) or {} if ref else {}

        except Exception as e:
            logger.error(f"[Skynet] execute failed for action={action}: {e}")

        return {}

    # ── Session helpers ───────────────────────────────────────────────────────

    def _fill_from_session(self, entities: dict, session: dict) -> dict:
        if not entities.get("sku_code") and session.get("last_sku"):
            entities["sku_code"] = session["last_sku"]
        if not entities.get("distributor_code") and session.get("last_distributor"):
            entities["distributor_code"] = session["last_distributor"]
        return entities

    def _update_session(self, session: dict, intent: str, action: str, entities: dict, sku_data: dict):
        if entities.get("sku_code"):
            session["last_sku"] = entities["sku_code"]
        if entities.get("distributor_code"):
            session["last_distributor"] = entities["distributor_code"]

        if action == "request_confirm":
            session["pending_order"] = {
                "sku_code":         entities.get("sku_code"),
                "distributor_code": entities.get("distributor_code"),
                "quantity":         entities.get("quantity"),
            }
        if action == "place_order":
            session["pending_order"] = None