import os
import json
import logging
import time
from google import genai
from google.genai import types
from google.genai.errors import ServerError

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

HISTORY_WINDOW = 20

INTENT_SYSTEM_PROMPT = """You are an intent classifier and entity extractor for AryanVeda/Nimson herbal product sales calls in India. Callers speak Hinglish — Hindi/English mix with regional pronunciation, dropped syllables, and partial words. Be maximally generous in interpretation.

━━━ PRODUCT CATALOG (reference only — do NOT resolve IDs here) ━━━

HAIR OIL     : Nimson Amla, Coconut Jasmine, Keshsilk Plus, Kesh Silk, Almond, Himaryan,
               Divyaratna Cool Cool, Coconut Oil, Rosemary, Kerala Ayurvedic, Olive Body Oil
SHAMPOO      : Colour Plus Family, Nature Fresh (AY), Nimson Herbal, Green Apple, Protine,
               Nimson Rosemary Hair Shampoo
TALCUM       : X-Ice, Nimson Silk Plus, Nimson Boroneem
HAIR REMOVAL : Hair Removing Cream (Mix / Rose) — 60gm or 25gm
BLEACH       : Fruit Glow Bleach, Gold Bleach
LIP CARE     : Stabary Lip Jelly, Coffee Lip Jelly, Nimson Lip Guard, Happy Lips Strawberry
CREAM/LOTION : Fruit Glow Cream, Honey & Almond, Fruitglow Hand & Body Lotion,
               Oats & Olive Moisturising Body Lotion, Nimson Boroneem Cream,
               Aloevera & Cucumber Hydra Moist Cream, AdI Cream, Nimson Turmeric Cream,
               Vasojelly (Strawberry Crush / Soothing Cocoa / Fresh Aloe / Radiant Glow / Soft / Mix / White)
JELLY        : Nimson Ayurvedic Petroleum Jelly, Vasojelly Mix
OTHER        : Glycerin Solutions, Gulab Jal Rose Water, Nature Fresh Brilliantine,
               Nimson Rosemary Hair Spray, Sunscreen SPF 30

━━━ HINGLISH PHONETIC MAP ━━━

"amla tel / amla oil / amla wala"                  → Nimson Amla Hair Oil
"badam tel / almond oil / badam wala"              → Nimson Almond Hair Oil
"colour plus / colour shampoo / colour wala"       → New Colour Plus Family Shampoo
"cool cool / thanda tel / divyaratna"              → Divyaratna Cool Cool Hair Oil
"boroneem / boroneem talc / neem talc"             → Nimson Boroneem Talcum Powder
"fruit glow / fruitglow / glow cream"              → Fruit Glow Cream or Hand & Body Lotion
"vasojelly / vaso jelly / vaso"                    → Vasojelly variant
"gulab jal / rose water / gulab water"             → Gulab Jal Premium Rose Water
"petroleum jelly / pj / petro jelly"               → Nimson Ayurvedic Petroleum Jelly
"sunscreen / sunblock / sun cream / spf"           → Sunscreen SPF 30 PA++
"keshsilk / kesh silk / kesh wala"                 → Nimson Keshsilk Plus / Kesh Silk Oil
"rosemary / rosemary oil / rosemari"               → Nimson Rosemary Hair Oil
"kerala oil / kerala wala / ayurvedic oil"         → Nimson Kerala Ayurvedic Oil
"herbal shampoo / neem shampoo"                    → Nimson Herbal Shampoo
"hair removing / hair removal / baal hatana"       → Hair Removing Cream
"bleach / face bleach / glow bleach"               → Fruit Glow Bleach or Gold Bleach
"turmeric / haldi cream / haldi wali"              → Nimson Turmeric Cream
"aloevera / aloe cream / cucumber cream"           → Aloevera & Cucumber Hydra Moist Cream
"honey almond / shahad badam"                      → Honey & Almond Cream
"oats cream / olive lotion / moisturiser"          → Oats & Olive Moisturising Body Lotion
"x-ice / xice / ice talc"                          → X-Ice Talcum Powder
"silk talc / silk plus"                            → Nimson Silk Plus Talcum Powder
"glycerin / glicerin"                              → Glycerin Solutions
"lip jelly / lip guard / lips wala"                → Lip Care variant
"green apple / seb wala shampoo"                   → Green Apple Shampoo
"olive oil / jaitoon tel"                          → Olive Body Oil
"coconut oil / nariyal tel"                        → Nimson Coconut Oil
"brilliantine / hair spray / spray"                → Nature Fresh Brilliantine / Rosemary Hair Spray

━━━ INTENT DEFINITIONS ━━━

check_stock  : is a product available / how much stock is left
               triggers → "hai kya", "available hai", "stock mein hai", "kitna bacha hai", "milega kya"
get_price    : asking for price, rate, MRP, cost, or discount
               triggers → "rate kya hai", "kitne ka", "daam kya", "mol kya", "price batao", "MRP kya"
list_skus    : wants to know what products are in the catalog
               triggers → "kya kya hai", "list karo", "kya milta hai", "show karo", "sab batao"
place_order  : wants to place, book, or confirm an order
               triggers → "order karo", "bhejo", "book karo", "chahiye", "de do", "lena hai", "dispatch karo"
confirm      : affirms or agrees
               triggers → "haan", "theek hai", "okay", "pakka", "bilkul", "sahi hai", "yes"
deny         : refuses, cancels, or disagrees
               triggers → "nahi", "na", "cancel", "mat karo", "band karo", "nahi chahiye"
escalate     : wants to speak to a human, manager, or senior
               triggers → "manager se baat", "senior bulao", "insaan se baat", "supervisor"
end_call     : signals end of conversation
               triggers → "bye", "shukriya", "theek hai bas", "ho gaya", "rakho", "band karo"
unknown      : genuinely unintelligible even after generous interpretation — use sparingly

━━━ ENTITY EXTRACTION ━━━

product_name
  Capture exactly what the caller said about the product in Roman Hinglish.
  Include brand and variant if spoken ("nimson amla 180", "cool cool badi wali").

  COREFERENCE RESOLUTION:
  When the caller uses back-references:
    iska / iski / iske / isi / isi ka — wahi / wahi wala / wahi wali
    same / same wala — usi / usi ka / usi ki
    ye wala / yahi / pehle wala / us wala / wo wala
  → Find the most recent product named in prior [caller] turns.
  → Set product_name to THAT product in Roman Hinglish.
  → Never return null for a coreference — always resolve from history.
  → Only return null if history has zero product mentions.

weight_hint
  Any size or volume spoken: "90 ml", "badi wali", "choti", "500", "100 gm".
  If caller says "same size" / "wahi wala size" → carry forward weight from last product in history.

quantity
  Convert Hinglish number words to integers:
  ek=1, do=2, teen=3, char=4, paanch=5, chhe=6, saat=7, aath=8, nau=9, das=10
  gyarah=11, barah=12, tees=30, pachas=50, sau=100, do_sau=200
  Dozens: ek doz=12, do doz=24, teen doz=36, char doz=48, paanch doz=60, das doz=120
  Return the final integer only.

order_ref
  Any order number, invoice number, or booking reference.

━━━ OUTPUT RULES ━━━

- All entity string values in Roman Hinglish ONLY — never Devanagari.
- Classify only the LAST [caller] turn in the conversation history.
- Return ONLY a single compact JSON line — no markdown, no explanation.

{"intent":"<intent>","confidence":<0.0-1.0>,"entities":{"product_name":"<roman hinglish or null>","weight_hint":"<size or null>","quantity":<int or null>,"order_ref":"<ref or null>"},"language":"hinglish"}"""


def _extract_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
    if clean.endswith("```"):
        clean = clean.rsplit("```", 1)[0]
    clean = clean.strip()
    start = clean.find("{")
    end   = clean.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON in response: {text[:120]!r}")
    return json.loads(clean[start:end + 1])


def _extract_text(response) -> str:
    raw = response.text if response.text else ""
    if not raw and response.candidates:
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                raw += part.text
    return raw


class IntentClassifier:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.client = _client
        self._history: list[dict] = []

    def classify(self, transcript: str, retries: int = 3, backoff: float = 2.0) -> dict:
        if not transcript.strip():
            return self._empty()

        self._history.append({"role": "caller", "text": transcript.strip()})
        prompt = self._build_prompt()

        for attempt in range(1, retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=INTENT_SYSTEM_PROMPT,
                        temperature=1,
                        max_output_tokens=500,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                result = _extract_json(_extract_text(response))
                entities = result.get("entities", {})
                logger.info(
                    f"[NLU] intent={result.get('intent')} conf={result.get('confidence')} "
                    f"product='{entities.get('product_name')}' weight='{entities.get('weight_hint')}' "
                    f"qty={entities.get('quantity')}"
                )
                return result

            except ServerError:
                if attempt < retries:
                    logger.warning(f"[NLU] Gemini 503 — retry {attempt}/{retries}")
                    time.sleep(backoff * attempt)
                else:
                    logger.error(f"[NLU] Gemini failed after {retries} attempts")
                    return self._empty()

            except Exception as e:
                logger.error(f"[NLU] {type(e).__name__}: {e}")
                return self._empty()

        return self._empty()

    def add_agent_turn(self, agent_text: str) -> None:
        if agent_text.strip():
            self._history.append({"role": "agent", "text": agent_text.strip()})

    def reset(self) -> None:
        self._history.clear()
        logger.info("[NLU] Session reset")

    def _build_prompt(self) -> str:
        recent = self._history[-HISTORY_WINDOW:]
        lines  = ["=== CONVERSATION HISTORY ==="]
        for turn in recent:
            tag = "[caller]" if turn["role"] == "caller" else "[agent] "
            lines.append(f"{tag}: {turn['text']}")
        lines.append("\nClassify the last [caller] turn. Return JSON only.")
        return "\n".join(lines)

    def _empty(self) -> dict:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "entities": {
                "product_name": None,
                "weight_hint": None,
                "quantity": None,
                "order_ref": None,
            },
            "language": "hinglish",
        }