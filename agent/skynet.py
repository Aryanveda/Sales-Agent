import logging
import time
import json
from typing import Optional
from stt.transcriber import Transcriber
from nlu.intent import IntentClassifier
from nlu.entities import EntityResolver
from tts.synthesizer import TTSPipeline
from agent.prompt import SYSTEM_PROMPT, RESPONSE_TEMPLATE
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

_client = genai.Client(api_key=__import__('os').getenv("GEMINI_API_KEY"))


# ─────────────────────────────────────────────────────────────────────────────
# In-memory conversation state (one per active call)
# ─────────────────────────────────────────────────────────────────────────────

class ConversationMemory:
    def __init__(self, session_id: str):
        self.session_id        = session_id
        self.turn              = 0
        self.products_discussed = []
        self.last_intent       = None
        self.last_product      = None
        self.pending_confirmation = False
        self.pending_action    = None
        self.history           = []          # last 5 turns kept in-memory
        self.caller_history    = []          # loaded from call.db at session start

    def add_turn(self, transcript: str, intent: str, product: Optional[str]):
        self.turn += 1
        self.last_intent = intent
        if product and product not in self.products_discussed:
            self.products_discussed.append(product)
        if product:
            self.last_product = product
        self.history.append({
            "turn":       self.turn,
            "transcript": transcript,
            "intent":     intent,
            "product":    product,
        })

    def context(self) -> dict:
        return {
            "turn":                 self.turn,
            "last_intent":          self.last_intent,
            "last_product":         self.last_product,
            "products_discussed":   self.products_discussed,
            "pending_confirmation": self.pending_confirmation,
            "history":              self.history[-5:] if len(self.history) > 5 else self.history,
            "caller_history":       self.caller_history,   # previous-call context
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main agent
# ─────────────────────────────────────────────────────────────────────────────

class Skynet:
    def __init__(self):
        logger.info("[Agent] Initializing Skynet...")
        self.transcriber        = Transcriber()
        self.intent_classifier  = IntentClassifier()
        self.entity_resolver    = EntityResolver()
        self.tts                = TTSPipeline()
        self._client            = _client
        logger.info("[Agent] Skynet ready.")

    # ── Session creation ─────────────────────────────────────────────────────

    def new_session(
        self,
        session_id:      str,
        db_session_id:   Optional[str]  = None,
        phone:           str            = "unknown",
        session_manager                 = None,     # db.session_manager.SessionManager | None
    ) -> dict:
        memory = ConversationMemory(session_id)

        # Load previous call history for this caller from call.db
        if session_manager and phone and phone != "unknown":
            try:
                memory.caller_history = session_manager.get_caller_history(phone, n=3)
                logger.info(f"[Session] Loaded {len(memory.caller_history)} past calls for {phone}")
            except Exception as e:
                logger.warning(f"[Session] Could not load caller history: {e}")

        # Reset NLU + entity state for the new session
        self.intent_classifier.reset()
        self.entity_resolver.reset()

        return {
            "session_id":      session_id,
            "db_session_id":   db_session_id,    # row id in call.db sessions table
            "phone":           phone,
            "turn":            0,
            "memory":          memory,
            "last_product_id":   None,
            "last_product_data": None,
            "last_entities":     None,
            "session_manager":   session_manager,
        }

    # ── Audio turn (live call) ───────────────────────────────────────────────

    def run_turn(self, audio_bytes: bytes, session: dict) -> dict:
        start_time = time.time()

        # STT — use streaming transcriber for live call chunks
        transcript_result = self.transcriber.transcribe_stream(audio_bytes)
        transcript        = transcript_result["text"]
        stt_confidence    = transcript_result["confidence"]
        logger.info(f"[STT] '{transcript}' (conf={stt_confidence:.2f})")

        session["turn"] += 1

        # NLU
        intent_result = self.intent_classifier.classify(transcript)
        intent        = intent_result["intent"]
        nlu_entities  = intent_result["entities"]
        logger.info(f"[NLU] intent={intent}")

        # Entity resolution
        entity_result = self.entity_resolver.resolve(nlu_entities)
        entities      = self._merge_entities(entity_result, session)
        logger.info(f"[Entity] product={entities.get('product_name')}")

        # Response generation
        response_result = self._generate_response(intent, transcript, entities, session)
        response_text   = response_result["response"]
        followup_text   = response_result.get("followup")

        # TTS
        audio_out = self.tts.synthesizer.speak(response_text)
        if followup_text:
            audio_out += self.tts.synthesizer.speak(followup_text)

        # Update in-memory state
        session["memory"].add_turn(transcript, intent, entities.get("product_name"))
        session["last_entities"]    = entities
        session["last_product_data"] = entity_result

        # 7. Feed agent reply into all downstream modules for next turn:
        full_reply = response_text + (" " + followup_text if followup_text else "")

        # NLU: agent turn in history enables coreference ("wahi wala", "iska")
        self.intent_classifier.add_agent_turn(full_reply)

        # Entity resolver: session history for context-aware product lookup
        self.entity_resolver.share_history(session["memory"].history)

        # STT: agent reply anchors Roman script for next caller turn
        self.transcriber.set_context(full_reply)

        # ── Persist to call.db ───────────────────────────────────────────────
        sm     = session.get("session_manager")
        db_sid = session.get("db_session_id")
        if sm and db_sid:
            turn_idx = session["turn"] - 1   # 0-based
            try:
                # Caller turn
                sm.save_turn(
                    session_id  = db_sid,
                    turn_index  = turn_idx,
                    speaker     = "caller",
                    text        = transcript,
                    confidence  = stt_confidence,
                )
                # Agent turn (index + 0.5 conceptually; store as next integer)
                sm.save_turn(
                    session_id  = db_sid,
                    turn_index  = turn_idx + 1,
                    speaker     = "agent",
                    text        = response_text + (" " + followup_text if followup_text else ""),
                    confidence  = None,
                )
                # Persist intent to session_context
                sm.set_context(db_sid, "last_intent",  intent)
                sm.set_context(db_sid, "last_product", entities.get("product_name") or "")
            except Exception as e:
                logger.warning(f"[DB] Failed to persist turn: {e}")
        # ────────────────────────────────────────────────────────────────────

        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[Turn] Latency={latency_ms}ms")

        return {
            "transcript":    transcript,
            "intent":        intent,
            "entities":      entities,
            "response_text": response_text,
            "followup_text": followup_text,
            "audio_bytes":   audio_out,
            "latency_ms":    latency_ms,
            "end_call":      intent == "end_call",
        }

    # ── Text turn (test / dev) ───────────────────────────────────────────────

    def run_turn_text(self, text: str, session: dict) -> dict:
        start_time = time.time()

        session["turn"] += 1

        intent_result = self.intent_classifier.classify(text)
        intent        = intent_result["intent"]
        nlu_entities  = intent_result["entities"]

        entity_result = self.entity_resolver.resolve(nlu_entities)
        entities      = self._merge_entities(entity_result, session)

        response_result = self._generate_response(intent, text, entities, session)
        response_text   = response_result["response"]
        followup_text   = response_result.get("followup")

        session["memory"].add_turn(text, intent, entities.get("product_name"))
        session["last_entities"]     = entities
        session["last_product_data"] = entity_result

        # Keep NLU + entity state in sync even for text turns
        full_reply = response_text + (" " + followup_text if followup_text else "")
        self.intent_classifier.add_agent_turn(full_reply)
        self.entity_resolver.share_history(session["memory"].history)

        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "transcript":    text,
            "intent":        intent,
            "entities":      entities,
            "response_text": response_text,
            "followup_text": followup_text,
            "latency_ms":    latency_ms,
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _merge_entities(self, entity_result: dict, session: dict) -> dict:
        entities = entity_result.copy()
        if not entities.get("product_id") and session.get("last_product_id"):
            entities["product_id"]   = session["last_product_id"]
            entities["product_name"] = session["last_product_data"].get("product_name")
            entities["weight"]       = session["last_product_data"].get("weight")
            logger.info("[Entity] Using cached product from session")
        return entities

    def _generate_response(self, intent: str, transcript: str, entities: dict, session: dict) -> dict:
        context = session["memory"].context()

        # Summarise caller history for the prompt (last 3 calls, last 2 turns each)
        caller_history_summary = "None"
        if context.get("caller_history"):
            lines = []
            for past in context["caller_history"]:
                snippet = past.get("last_turns", [])[-2:]
                for t in snippet:
                    lines.append(f"  [{t['speaker']}]: {t['text']}")
            if lines:
                caller_history_summary = "\n".join(lines)

        prompt_text = RESPONSE_TEMPLATE.format(
            previous_products      = ", ".join(context.get("products_discussed", [])) or "none",
            last_intent            = context.get("last_intent") or "none",
            turn                   = context.get("turn"),
            intent                 = intent,
            product_name           = entities.get("product_name") or "not specified",
            weight                 = entities.get("weight") or "not specified",
            quantity               = entities.get("quantity") or "not specified",
            entities               = json.dumps(entities),
            caller_history_summary = caller_history_summary,
        )

        # If entity resolution returned multiple candidates (ambiguous weight),
        # build a clarification response directly — no need to call Gemini.
        candidates = entities.get("candidates", [])
        if candidates and not entities.get("product_id"):
            # Extract clean weight list from candidate strings  "id:Name Weight"
            weights = []
            for c in candidates:
                parts = c.split(":", 1)
                label = parts[1] if len(parts) > 1 else c
                # grab the weight token at the end e.g. "Nimson Amla Hair Oil 180 ml"
                tokens = label.strip().split()
                if tokens:
                    weights.append(" ".join(tokens[-2:]) if len(tokens) >= 2 else tokens[-1])
            weight_list = ", ".join(weights) if weights else "alag alag sizes"
            product_name = entities.get("product_name") or "product"
            return {
                "response": f"{product_name} ke liye size batao — {weight_list} available hain.",
                "followup": None,
                "needs_confirmation": True,
            }

        try:
            response = self._client.models.generate_content(
                model    = "gemini-2.5-flash",
                contents = prompt_text,
                config   = types.GenerateContentConfig(
                    system_instruction = SYSTEM_PROMPT,
                    temperature        = 0.4,
                    max_output_tokens  = 300,
                    response_mime_type = "application/json",
                ),
            )

            # Safely extract text — response.text can be None if Gemini blocked output
            raw_text = None
            if response.text:
                raw_text = response.text.strip()
            elif response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        raw_text = part.text.strip()
                        break

            if not raw_text:
                logger.warning("[Response] Gemini returned empty text — using fallback")
                return {"response": self._fallback_response(intent, entities), "followup": None}

            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
                raw_text = raw_text.strip()

            result        = json.loads(raw_text)
            response_text = result.get("response", "Samajh nahi aaya, ek baar phir se batao.")
            followup_text = result.get("followup")

            logger.info(f"[Response] '{response_text[:60]}...'")
            return {
                "response":           response_text,
                "followup":           followup_text,
                "needs_confirmation": result.get("needs_confirmation", False),
            }

        except json.JSONDecodeError as e:
            logger.error(f"[Response] JSON parse failed: {e}")
            return {"response": self._fallback_response(intent, entities), "followup": None}

        except Exception as e:
            logger.error(f"[Response] Generation failed: {e}")
            return {"response": self._fallback_response(intent, entities), "followup": None}

    def _fallback_response(self, intent: str, entities: dict) -> str:
        product = entities.get("product_name", "product")
        weight  = entities.get("weight", "")
        qty     = entities.get("quantity", "")

        fallbacks = {
            "check_stock": f"Bhai, {product} {weight} stock mein available hai. Order karo?",
            "get_price":   f"{product} {weight} ka MRP rupaye batata hoon ek second.",
            "place_order": f"Bilkul! {qty} piece {product} {weight} order confirm kar du?",
            "list_skus":   "Hamare paas bahut products hain. Kaunsa chahiye?",
            "confirm":     "Theek hai bhai, order process ho raha hai.",
            "deny":        "Koi baat nahi. Aur kuch chahiye?",
            "escalate":    "Manager ko bulata hun ek second.",
            "end_call":    "Shukriya! AryanVeda mein call karne ke liye.",
            "unknown":     "Samajh nahi aaya. Ek baar phir se batao.",
        }
        return fallbacks.get(intent, "Ek second, samajhta hoon kya kehna chahte ho.")