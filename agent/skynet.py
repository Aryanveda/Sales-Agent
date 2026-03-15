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

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=__import__('os').getenv("GEMINI_API_KEY"))


class ConversationMemory:
    def __init__(self, session_id: str):
        self.session_id           = session_id
        self.turn                 = 0
        self.products_discussed   = []
        self.last_intent          = None
        self.last_product         = None
        self.pending_confirmation = False
        self.history              = []
        self.caller_history       = []

    def add_turn(self, transcript: str, intent: str, product: Optional[str]):
        self.turn        += 1
        self.last_intent  = intent
        if product and product not in self.products_discussed:
            self.products_discussed.append(product)
        if product:
            self.last_product = product
        self.history.append({"turn": self.turn, "transcript": transcript, "intent": intent, "product": product})

    def context(self) -> dict:
        return {
            "turn":                 self.turn,
            "last_intent":          self.last_intent,
            "last_product":         self.last_product,
            "products_discussed":   self.products_discussed,
            "pending_confirmation": self.pending_confirmation,
            "history":              self.history,
            "caller_history":       self.caller_history,
        }


class Skynet:
    def __init__(self):
        logger.info("[Agent] Initializing Skynet...")
        self.transcriber       = Transcriber()
        self.intent_classifier = IntentClassifier()
        self.entity_resolver   = EntityResolver()
        self.tts               = TTSPipeline()
        self._client           = _client
        logger.info("[Agent] Skynet ready.")

    def new_session(self, session_id: str, db_session_id: Optional[str] = None,
                    phone: str = "unknown", session_manager=None) -> dict:
        memory = ConversationMemory(session_id)
        if session_manager and phone and phone != "unknown":
            try:
                memory.caller_history = session_manager.get_caller_history(phone, n=3)
                logger.info(f"[Session] Loaded {len(memory.caller_history)} past calls for {phone}")
            except Exception as e:
                logger.warning(f"[Session] Could not load caller history: {e}")
        return {
            "session_id":        session_id,
            "db_session_id":     db_session_id,
            "phone":             phone,
            "turn":              0,
            "memory":            memory,
            "last_product_id":   None,
            "last_product_data": None,
            "last_entities":     None,
            "session_manager":   session_manager,
        }

    def run_turn(self, audio_bytes: bytes, session: dict) -> dict:
        t0                = time.time()
        transcript_result = self.transcriber.transcribe_stream(audio_bytes)
        transcript        = transcript_result["text"]
        stt_confidence    = transcript_result["confidence"]
        logger.info(f"[STT] '{transcript}' conf={stt_confidence:.2f}")

        session["turn"] += 1

        intent_result = self.intent_classifier.classify(transcript)
        intent        = intent_result["intent"]
        nlu_entities  = intent_result["entities"]

        entity_result = self.entity_resolver.resolve(nlu_entities)
        entities      = self._merge_entities(entity_result, session)

        response_result = self._generate_response(intent, transcript, entities, session)
        response_text   = response_result["response"]
        followup_text   = response_result.get("followup")

        audio_out = self.tts.synthesizer.speak(response_text)
        if followup_text:
            audio_out += self.tts.synthesizer.speak(followup_text)

        session["memory"].add_turn(transcript, intent, entities.get("product_name"))
        session["last_entities"]     = entities
        session["last_product_data"] = entity_result

        full_reply = response_text + (" " + followup_text if followup_text else "")
        self.intent_classifier.add_agent_turn(full_reply)
        self.entity_resolver.share_history(session["memory"].history)
        self.transcriber.set_context(full_reply)

        sm     = session.get("session_manager")
        db_sid = session.get("db_session_id")
        if sm and db_sid:
            idx = session["turn"] - 1
            try:
                sm.save_turn(db_sid, idx,     "caller", transcript, stt_confidence)
                sm.save_turn(db_sid, idx + 1, "agent",  full_reply)
                sm.set_context(db_sid, "last_intent",  intent)
                sm.set_context(db_sid, "last_product", entities.get("product_name") or "")
            except Exception as e:
                logger.warning(f"[DB] Failed to persist turn: {e}")

        latency = int((time.time() - t0) * 1000)
        logger.info(f"[Turn] Latency={latency}ms")
        return {
            "transcript":    transcript,
            "intent":        intent,
            "entities":      entities,
            "response_text": response_text,
            "followup_text": followup_text,
            "audio_bytes":   audio_out,
            "latency_ms":    latency,
            "end_call":      intent == "end_call",
        }

    def run_turn_text(self, text: str, session: dict) -> dict:
        t0 = time.time()
        session["turn"] += 1

        intent_result   = self.intent_classifier.classify(text)
        intent          = intent_result["intent"]
        entity_result   = self.entity_resolver.resolve(intent_result["entities"])
        entities        = self._merge_entities(entity_result, session)
        response_result = self._generate_response(intent, text, entities, session)
        response_text   = response_result["response"]
        followup_text   = response_result.get("followup")

        session["memory"].add_turn(text, intent, entities.get("product_name"))
        session["last_entities"]     = entities
        session["last_product_data"] = entity_result

        full_reply = response_text + (" " + followup_text if followup_text else "")
        self.intent_classifier.add_agent_turn(full_reply)
        self.entity_resolver.share_history(session["memory"].history)

        return {
            "transcript":    text,
            "intent":        intent,
            "entities":      entities,
            "response_text": response_text,
            "followup_text": followup_text,
            "latency_ms":    int((time.time() - t0) * 1000),
        }

    def _merge_entities(self, entity_result: dict, session: dict) -> dict:
        entities = entity_result.copy()
        if not entities.get("product_id") and session.get("last_product_id"):
            entities["product_id"]   = session["last_product_id"]
            entities["product_name"] = session["last_product_data"].get("product_name")
            entities["weight"]       = session["last_product_data"].get("weight")
        return entities

    def _build_conversation_transcript(self, history: list, max_turns: int = 30) -> str:
        """
        Build a readable dialogue transcript from session history.
        If history exceeds max_turns, summarise older turns and keep recent ones verbatim.
        This ensures context is never lost regardless of call length.
        """
        if not history:
            return "No prior turns."

        if len(history) <= max_turns:
            lines = []
            for h in history:
                lines.append(f"[Turn {h['turn']}] Caller: {h['transcript']}")
                if h.get("intent"):
                    lines.append(f"  Intent: {h['intent']} | Product: {h.get('product') or '-'}")
            return "\n".join(lines)

        # Long call: summarise old turns, keep last max_turns verbatim
        old_turns    = history[:-max_turns]
        recent_turns = history[-max_turns:]

        products_mentioned = list(dict.fromkeys(
            h["product"] for h in old_turns if h.get("product")
        ))
        intents_seen = list(dict.fromkeys(
            h["intent"] for h in old_turns if h.get("intent")
        ))
        summary = (
            f"[Earlier {len(old_turns)} turns summary] "
            f"Products discussed: {', '.join(products_mentioned) or 'none'}. "
            f"Intents seen: {', '.join(intents_seen) or 'none'}."
        )

        lines = [summary, "\n[Recent turns:]"]
        for h in recent_turns:
            lines.append(f"[Turn {h['turn']}] Caller: {h['transcript']}")
            if h.get("intent"):
                lines.append(f"  Intent: {h['intent']} | Product: {h.get('product') or '-'}")
        return "\n".join(lines)

    def _generate_response(self, intent: str, transcript: str, entities: dict, session: dict) -> dict:
        from datetime import datetime, timezone, timedelta
        IST     = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(tz=IST)
        context = session["memory"].context()

        caller_history_summary = "None"
        if context.get("caller_history"):
            lines = []
            for past in context["caller_history"]:
                for t in past.get("last_turns", [])[-2:]:
                    lines.append(f"  [{t['speaker']}]: {t['text']}")
            if lines:
                caller_history_summary = "\n".join(lines)

        candidates = entities.get("candidates") or []
        if candidates and not entities.get("product_id"):
            weights = []
            for c in candidates:
                parts  = c.split(":", 1)
                label  = parts[1] if len(parts) > 1 else c
                tokens = label.strip().split()
                if tokens:
                    weights.append(" ".join(tokens[-2:]) if len(tokens) >= 2 else tokens[-1])
            wlist = ", ".join(weights) if weights else "alag alag sizes"
            return {
                "response": f"{entities.get('product_name') or 'product'} ke liye size batao sir — {wlist} available hain.",
                "followup": None,
                "needs_confirmation": True,
            }

        convo_transcript = self._build_conversation_transcript(context.get("history", []))

        prompt = RESPONSE_TEMPLATE.format(
            previous_products      = ", ".join(context.get("products_discussed", [])) or "none",
            last_intent            = context.get("last_intent") or "none",
            turn                   = context.get("turn"),
            transcript             = transcript,
            intent                 = intent,
            product_name           = entities.get("product_name") or "not specified",
            weight                 = entities.get("weight") or "not specified",
            quantity               = entities.get("quantity") or "not specified",
            entities               = json.dumps(entities),
            caller_history_summary = caller_history_summary,
            conversation_transcript = convo_transcript,
            current_date           = now_ist.strftime("%A, %d %B %Y"),
            current_time           = now_ist.strftime("%I:%M %p IST"),
        )

        try:
            response = self._client.models.generate_content(
                model    = "gemini-2.5-flash",
                contents = prompt,
                config   = types.GenerateContentConfig(
                    system_instruction = SYSTEM_PROMPT,
                    temperature        = 0.4,
                    max_output_tokens  = 300,
                    response_mime_type = "application/json",
                ),
            )
            raw = response.text
            if not raw and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        raw = part.text.strip()
                        break
            if not raw:
                logger.warning("[Response] Gemini returned empty text")
                return {"response": self._fallback(intent, entities), "followup": None}

            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            start = raw.find("{")
            end   = raw.rfind("}")
            if start != -1 and end != -1:
                raw = raw[start:end + 1]

            raw    = raw.replace("₹", "rupaye ")
            result = json.loads(raw)
            text   = result.get("response", "Samajh nahi aaya sir, ek baar phir se batao.")
            logger.info(f"[Response] '{text[:60]}...'")
            return {"response": text, "followup": result.get("followup"),
                    "needs_confirmation": result.get("needs_confirmation", False)}

        except json.JSONDecodeError as e:
            logger.error(f"[Response] JSON parse failed: {e}")
            if intent == "confirm":
                p = entities.get("product_name", "product")
                w = entities.get("weight", "")
                q = entities.get("quantity", "")
                return {"response": f"Bilkul sir! {q} piece {p} {w} ka order confirm ho gaya. Shukriya ji!", "followup": None}
            return {"response": self._fallback(intent, entities), "followup": None}

        except Exception as e:
            logger.error(f"[Response] Generation failed: {e}")
            return {"response": self._fallback(intent, entities), "followup": None}

    def _fallback(self, intent: str, entities: dict) -> str:
        p = entities.get("product_name")
        w = entities.get("weight", "")
        q = entities.get("quantity")

        if intent == "check_stock":
            if p:
                return f"{p} {w} stock mein available hai sir. Order karte hain?".strip()
            return "Kaunsa product ka stock check karna hai sir?"

        if intent == "get_price":
            if p:
                return f"{p} {w} ka price batata hoon sir.".strip()
            return "Kaunse product ka price chahiye sir?"

        if intent == "place_order":
            if p and q:
                return f"Zaroor sir! {q} piece {p} {w} ka order confirm kar doon?".strip()
            if p:
                return f"{p} ka order karna hai — kitne pieces chahiye sir?"
            return "Zaroor sir, kaunsa product aur kitni quantity chahiye?"

        return {
            "list_skus": "Hamare paas hair oils, shampoos, creams, face wash aur bahut kuch hai sir. Kaunsi category dekhni hai?",
            "confirm":   "Theek hai sir, ho jayega. Shukriya ji!",
            "deny":      "Koi baat nahi sir. Aur kuch kaam ho toh batao.",
            "escalate":  "Zaroor sir, manager se connect karta hoon. Ek moment.",
            "end_call":  "Shukriya ji! AryanVeda mein call karne ke liye. Aapka din accha ho!",
            "unknown":   "Haan sir, batao — kaise madad kar sakta hoon?",
        }.get(intent, "Haan sir, boliye — kya chahiye aapko?")