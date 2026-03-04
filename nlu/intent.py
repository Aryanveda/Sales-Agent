import os
import json
import logging
from google import genai
from google.genai import types
from nlu.prompt import INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT

logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

KNOWLEDGE = """
DISTRIBUTORS:
- DIST_MUM_01 → mumbai, mumbai central, mumbai wale
- DIST_MUM_02 → mumbai suburban, suburban
- DIST_DEL_01 → delhi, delhi ncr, delhi wale
- DIST_DEL_02 → delhi south
- DIST_BLR_01 → bangalore, bengaluru
- DIST_HYD_01 → hyderabad
- DIST_CHN_01 → chennai
- DIST_PUN_01 → punjab, ludhiana
- DIST_GUJ_01 → gujarat, ahmedabad
- DIST_RAJ_01 → rajasthan, jaipur

SKUS:
AV-001=Crack Heel Cream 25gm, AV-002=Almond Hair Oil 100ml, AV-003=Almond Hair Oil 200ml,
AV-004=Almond Hair Oil 500ml, AV-005=Almond Olive Hair Oil 100ml, AV-006=Almond Olive Hair Oil 200ml,
AV-010=Amla Hair Oil 180ml, AV-011=Amla Hair Oil 20ml, AV-012=Amla Hair Oil 300ml,
AV-013=Amla Hair Oil 35ml, AV-014=Amla Hair Oil 450ml, AV-015=Amla Hair Oil 50ml,
AV-016=Amla Hair Oil 70ml, AV-017=Amla Hair Oil 90ml, AV-018=Amla Hair Oil 1Ltr,
AV-019=Apple Face Wash 60ml, AV-020=Body Guard Talcum 100gm, AV-029=Charcoal Face Wash 60gm,
AV-031=Coconut Oil 50ml, AV-032=Coconut Oil 90ml, AV-033=Coconut Oil 950ml, AV-034=Coconut Oil 500ml,
AV-037=Colour Plus Shampoo 180ml, AV-038=Colour Plus Shampoo 450ml,
AV-041=Divya Ratan Hair Oil 180ml, AV-047=Fair Gomarks Cream 25gm,
AV-054=Fruit Glow Cream 50gm, AV-055=Fruit Glow Cream 100gm,
AV-083=Jasmine Coconut Hair Oil 180ml, AV-092=Kesh Silk Hair Oil 180ml,
AV-101=Nature Fresh Shampoo 1000ml, AV-102=Nature Fresh Shampoo 180ml,
AV-104=Neem Tulsi Face Wash 60ml, AV-113=Petroleum Jelly 50gm,
AV-116=Rosemary Hair Growth Spray 110ml, AV-118=Rosemary Shampoo 250ml,
AV-119=Silk Plus Cold Cream 100gm, AV-121=Silk Plus Cold Cream 50gm,
AV-123=Silk Plus Rose Talcum 100gm, AV-129=Turmeric Cream 30gm,
AV-136=Vitamin C Face Wash 100gm, AV-143=X-Ice Talcum 100gm

INTENTS:
check_stock=stock availability query, get_price=price query,
list_skus=list products, place_order=place an order,
confirm=yes/haan/theek hai, deny=no/nahi/cancel,
escalate=wants human/manager, end_call=bye/thanks/bas, unknown=anything else
"""

CLEANUP_PROMPT = """Extract intent and entities from this AryanVeda sales call input.
Return ONLY compact single-line JSON, no whitespace, no explanation:
{{"intent":"<intent>","confidence":<float>,"entities":{{"sku_code":"<AV-XXX or null>","distributor_name":"<city or null>","quantity":<number or null>,"order_ref":"<ref or null>"}},"language":"hinglish"}}

Knowledge:
{knowledge}

Input: {raw}"""


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

    def classify(self, transcript: str) -> dict:
        if not transcript.strip():
            return self._empty()

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=CLEANUP_PROMPT.format(
                    knowledge=KNOWLEDGE,
                    raw=transcript,
                ),
                config=types.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=1000,   # increased — was 300, caused truncation
                    response_mime_type="application/json",
                ),
            )

            raw    = _extract_text(response)
            result = json.loads(raw)
            logger.info(f"[NLU] intent={result.get('intent')} sku={result.get('entities',{}).get('sku_code')} dist={result.get('entities',{}).get('distributor_name')}")
            return result

        except Exception as e:
            logger.error(f"[NLU] failed: {e}")
            return self._empty()

    def _empty(self) -> dict:
        return {
            "intent":     "unknown",
            "confidence": 0.0,
            "entities": {
                "sku_code":         None,
                "distributor_name": None,
                "quantity":         None,
                "order_ref":        None
            },
            "language": "hinglish"
        }