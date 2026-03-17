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

logger = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ================= MEMORY =================

class ConversationMemory:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.turn = 0
        self.history: List[Dict] = []

        self.current_product = None
        self.current_weight = None

    def update(self, transcript, intent, entity):
        self.turn += 1

        if entity.get("product_name"):
            self.current_product = entity["product_name"]

        if entity.get("weight"):
            self.current_weight = entity["weight"]

        self.history.append({
            "turn": self.turn,
            "text": transcript,
            "intent": intent,
            "product": self.current_product,
            "weight": self.current_weight
        })

    def context(self):
        return {
            "history": self.history,
            "current_product": self.current_product,
            "current_weight": self.current_weight
        }


# ================= SKYNET =================

class Skynet:
    def __init__(self):
        logger.info("[Agent] Initializing Skynet...")

        self.transcriber = Transcriber()
        self.intent_classifier = IntentClassifier()
        self.entity_resolver = EntityResolver()
        self.tts = TTSPipeline()
        self._client = _client

        DB_PATH = os.getenv("DB_PATH", "aryanveda.db")

        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Load structured knowledge
        self.knowledge_base = self._load_knowledge()

        logger.info(f"[DB] Connected → {DB_PATH}")
        logger.info(f"[KG] Loaded {len(self.knowledge_base)} products")
        logger.info("[Agent] Skynet ready.")


    # ================= KNOWLEDGE PARSER =================

    def _load_knowledge(self):
        path = os.path.join(os.path.dirname(__file__), "knowledge.txt")

        if not os.path.exists(path):
            logger.warning("[KG] knowledge.txt not found")
            return []

        with open(path, encoding="utf-8") as f:
            raw = f.read()

        blocks = raw.split("================================================================================")

        structured = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            try:
                if "PRODUCT:" not in block:
                    continue

                # extract name ONLY for matching
                product_name = block.split("PRODUCT:")[1].split("\n")[0].strip().lower()

                structured.append({
                    "product_name": product_name,
                    "raw_text": block   # ← FULL BLOCK PRESERVED
                })

            except Exception as e:
                logger.warning(f"[KG] parsing failed: {e}")

        return structured
    
    def _knowledge_fetch(self, product_name: Optional[str]):
        if not product_name:
            return None

        pname = product_name.lower()

        pname = pname.replace("tel", "oil").replace("badam", "almond")

        pname_tokens = set(pname.split())

        best_score = 0
        best_match = None

        for item in self.knowledge_base:
            kname = item["product_name"]
            k_tokens = set(kname.split())

            common = pname_tokens.intersection(k_tokens)

            if not common:
                continue

            score = len(common) / len(pname_tokens)

            if score > best_score:
                best_score = score
                best_match = item

        if best_score < 0.3:
            return None

        return best_match["raw_text"] if best_match else None

    def _format_knowledge(self, knowledge):
        if not knowledge:
            return "No additional product knowledge available."

        return knowledge

    # ================= DB FETCH =================

    def _db_fetch(self, query_text: str):
        try:
            rows = self.conn.execute("""
                SELECT product_name, weight, mrp_unit, retail
                FROM products
                WHERE LOWER(product_name) LIKE LOWER(?)
                LIMIT 20
            """, (f"%{query_text}%",)).fetchall()

            grouped = {}

            for r in rows:
                pname = r["product_name"]

                if pname not in grouped:
                    grouped[pname] = {
                        "product_name": pname,
                        "variants": [],
                        "pricing": []
                    }

                if r["weight"]:
                    grouped[pname]["variants"].append(r["weight"])

                grouped[pname]["pricing"].append({
                    "weight": r["weight"],
                    "mrp": r["mrp_unit"],
                    "retail": r["retail"]
                })

            return list(grouped.values())[:5]

        except Exception as e:
            logger.warning(f"[DB] Fetch failed: {e}")
            return []


    # ================= SESSION =================

    def new_session(self, session_id: str, db_session_id=None, session_manager=None, **kwargs):
        return {
            "session_id": session_id,
            "turn": 0,
            "memory": ConversationMemory(session_id),
            "db_session_id": db_session_id,
            "session_manager": session_manager
        }


    # ================= MAIN =================

    def run_turn_text(self, text: str, session: dict):
        t0 = time.time()

        memory = session["memory"]
        session["turn"] += 1

        intent_result = self.intent_classifier.classify(text)
        intent = intent_result["intent"]

        entity_result = self.entity_resolver.resolve(intent_result["entities"])

        # -------- CONTEXT RECOVERY --------
        if not entity_result.get("product_name"):
            entity_result["product_name"] = memory.current_product

        if not entity_result.get("weight"):
            entity_result["weight"] = memory.current_weight

        product_name = entity_result.get("product_name")

        # -------- HYBRID FETCH --------
        db_data = self._db_fetch(product_name or text)
        knowledge = self._knowledge_fetch(product_name)

        response = self._generate_response(
            transcript=text,
            db_data=db_data,
            knowledge=knowledge,
            entity=entity_result,
            memory=memory
        )

        memory.update(text, intent, entity_result)

        return {
            "transcript": text,
            "intent": intent,
            "entities": entity_result,
            "response_text": response["response"],
            "followup_text": response.get("followup"),
            "latency_ms": int((time.time() - t0) * 1000),
        }


    # ================= RESPONSE =================

    def _generate_response(self, transcript, db_data, knowledge, entity, memory):
        from datetime import datetime, timezone, timedelta

        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)

        context = memory.context()

        prompt = RESPONSE_TEMPLATE.format(
            conversation_transcript=self._build_conversation(context["history"]),
            transcript=transcript,
            db_data=json.dumps(db_data),
            knowledge=self._format_knowledge(knowledge),
            current_state=json.dumps({
                "product": context["current_product"],
                "weight": context["current_weight"]
            }),
            current_date=now.strftime("%A, %d %B %Y"),
            current_time=now.strftime("%I:%M %p IST"),
            caller_language="hinglish",
        )

        try:
            response = self._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                    response_mime_type="application/json",
                )
            )

            raw = getattr(response, "text", "").strip()

            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                raw = raw[start:end + 1]

            try:
                return json.loads(raw)
            except:
                return {
                    "response": "Samajh gaya sir — main aapko detail mein samjhata hoon.",
                    "followup": None
                }
                
        except Exception as e:
            logger.error(f"[LLM] Failed: {e}")
            return {
                "response": "Sir main samajh gaya, ek baar dobara batata hoon.",
                "followup": None
            }


    # ================= HELPERS =================

    def _build_conversation(self, history):
        lines = []
        for h in history[-10:]:
            lines.append(
                f"[Turn {h['turn']}] User: {h['text']} | Product: {h['product']} | Weight: {h['weight']}"
            )
        return "\n".join(lines)