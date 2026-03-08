import os
import json
import logging
import time
from google import genai
from google.genai import types
from google.genai.errors import ServerError

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


INTENT_PROMPT = """You are an intent + entity extractor for AryanVeda/Nimson sales calls in India.
Callers speak Hinglish — Hindi/English mix with pronunciation errors and partial words. Be very generous.

────────────────────────────────────────────────
PRODUCT FAMILIES (for reference — do NOT resolve to IDs here, just capture what was said):
  HAIR OIL    : Nimson Amla, Coconut Jasmine, Keshsilk Plus, Kesh Silk, Almond, Himaryan,
                Divyaratna Cool Cool, Coconut Oil, Rosemary, Kerala Ayurvedic, Olive Body Oil
  SHAMPOO     : Colour Plus Family, Nature Fresh (AY), Nimson Herbal, Green Apple, Protine,
                Nimson Rosemary Hair Shampoo
  TALCUM      : X-Ice, Nimson Silk Plus, Nimson Boroneem
  HAIR REMOVAL: Hair Removing Cream (Mix / Rose) — 60gm or 25gm
  BLEACH      : Fruit Glow Bleach, Gold Bleach
  LIP CARE    : Stabary Lip Jelly, Coffee Lip Jelly, Nimson Lip Guard, Happy Lips Strawberry
  CREAM/LOTION: Fruit Glow Cream, Honey & Almond, Fruitglow Hand & Body Lotion,
                Oats & Olive Moisturising Body Lotion, Nimson Boroneem Cream,
                Aloevera & Cucumber Hydra Moist Cream, AdI cream, Nimson Turmeric Cream,
                Vasojelly (Strawberry Crush / Soothing Cocoa / Fresh Aloe / Radiant Glow / Soft / Mix / White)
  JELLY       : Nimson Ayurvedic Petroleum Jelly, Vasojelly Mix
  OTHER       : Glycerin Solutions, Gulab Jal Rose Water, Nature Fresh Brilliantine,
                Nimson Rosemary Hair Spray, Sunscreen SPF 30

HINGLISH → PRODUCT HINTS (common pronunciations):
  "amla tel / amla oil"          → Nimson Amla Hair Oil
  "colour plus / colour shampoo" → New Colour Plus Family Shampoo
  "badam tel / almond oil"       → Nimson Almond Hair Oil
  "cool cool / thanda tel"       → Divyaratna Cool Cool Hair Oil
  "boroneem / boroneem talc"     → Nimson Boroneem Talcum Powder
  "fruit glow / fruitglow"       → Fruit Glow Cream or Fruitglow Hand & Body Lotion
  "vasojelly / vaso jelly"       → any Vasojelly variant
  "gulab jal / rose water"       → Gulab Jal Premium Rose water
  "petroleum jelly / pj"         → Nimson Ayurvedic Petroleum Jelly
  "sunscreen / sunblock"         → Sunscreen SPF 30 PA++
  "keshsilk / kesh silk"         → Nimson Keshsilk Plus / Kesh Silk Oil
  "rosemary oil / rosemary"      → Nimson Rosemary Hair Oil
  "kerala oil"                   → Nimson Kerala Ayurvedic Oil
  "neem shampoo / herbal shampoo"→ Nimson Herbal Shampoo or Neem Tulsi Face Wash
  "hair removing / hair removal" → Hair removing Cream
  "bleach"                       → Fruit Glow Bleach or Gold Bleach

────────────────────────────────────────────────
INTENTS (be generous, match loosely):
  check_stock  = availability / stock / quantity on hand ("hai kya", "kitna hai", "stock check", "available hai")
  get_price    = price / rate / cost / MRP / daam / dam / mol ("rate kya hai", "kitne ka", "price batao",
                 "daam kya hai", "daam batao", "kitna daam", "kya daam", "mol kya hai", "kya rate hai")
  list_skus    = list products / what do you have ("kya kya hai", "list karo", "show products")
  place_order  = wants to order / book / send / dispatch ("order karo", "bhejo", "book karo", "chahiye")
  confirm      = yes / theek hai / haan / okay / pakka / bilkul
  deny         = no / nahi / cancel / stop / mat karo / band karo
  escalate     = wants manager / senior / real person ("manager se baat", "senior bulao")
  end_call     = ending call / bye / shukriya / theek hai bas / done
  unknown      = genuinely unclear even with generous interpretation

────────────────────────────────────────────────
ENTITY EXTRACTION RULES:
  product_name : Capture EXACTLY what was said about the product — raw, unresolved.
                 Include brand + variant if mentioned ("nimson amla 180", "cool cool badi wali").
                 If caller says "iske" / "iska" / "iski" / "wahi wala" / "same" / "usi ka" /
                 "ye wala" / "yahi" → set to null (caller is referring to previous product in context).
  weight_hint  : Any size/volume mentioned separately ("90 ml", "badi wali 500", "choti", "180").
                 Extract even if embedded in product_name.
  quantity     : Any number with units. Convert Hindi words to integers:
                 "ek"=1, "do"=2, "teen"=3, "char"=4, "paanch"=5, "chhe"=6, "saat"=7,
                 "aath"=8, "nau"=9, "das"=10, "bees"=20, "pachas"=50, "sau"=100, "do sau"=200.
                 Dozen conversions: "ek doz/dozen/darjan"=12, "do doz"=24, "teen doz"=36,
                 "char doz"=48, "paanch doz"=60, "das doz"=120.
                 "10 dozen" = 120, "5 dozen" = 60.
                 Extract the final integer value only.
  order_ref    : Any order reference / invoice number if mentioned.

Return ONLY compact single-line JSON — no markdown fences, no explanation:
{{"intent":"<intent>","confidence":<0.0-1.0>,"entities":{{"product_name":"<raw spoken or null>","weight_hint":"<size spoken or null>","quantity":<number or null>,"order_ref":"<ref or null>"}},"language":"hinglish"}}

Input transcript: {transcript}"""


def _extract_text(response) -> str:
    raw = response.text if response.text else ""
    if not raw and response.candidates:
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                raw += part.text
    return raw


class IntentClassifier:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model  = model
        self.client = _client

    def classify(self, transcript: str, retries: int = 3, backoff: float = 2.0) -> dict:
        if not transcript.strip():
            return self._empty()

        last_error = None
        for attempt in range(1, retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=INTENT_PROMPT.format(transcript=transcript),
                    config=types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=500,
                        response_mime_type="application/json",
                    ),
                )
                raw    = _extract_text(response)
                result = json.loads(raw)

                entities = result.get("entities", {})
                logger.info(
                    f"[NLU] intent={result.get('intent')} conf={result.get('confidence')} "
                    f"product='{entities.get('product_name')}' "
                    f"weight='{entities.get('weight_hint')}' "
                    f"qty={entities.get('quantity')}"
                )
                return result

            except ServerError as e:
                last_error = e
                if attempt < retries:
                    wait = backoff * attempt
                    print(f"  [retry {attempt}/{retries}] Gemini 503 — retrying in {wait:.0f}s...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"  [error] Gemini unavailable after {retries} attempts: {e}", flush=True)

            except Exception as e:
                print(f"  [error] classify failed: {type(e).__name__}: {e}", flush=True)
                return self._empty()

        return self._empty()

    def _empty(self) -> dict:
        return {
            "intent":     "unknown",
            "confidence": 0.0,
            "entities": {
                "product_name": None,
                "weight_hint":  None,
                "quantity":     None,
                "order_ref":    None,
            },
            "language": "hinglish",
        }