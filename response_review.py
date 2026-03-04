"""
Quick debug script — run this standalone to see exactly what Gemini returns.
Place in Sales-Agent root and run: python intent_debug.py
"""
import os
import json
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PROMPT = """You are an intent extraction engine for AryanVeda sales calls.

From the input text extract and return ONLY this JSON (no explanation, no markdown):
{
  "intent": "check_stock",
  "confidence": 0.95,
  "entities": {
    "sku_code": "AV-010",
    "distributor_name": "mumbai",
    "quantity": null,
    "order_ref": null
  },
  "language": "hinglish"
}

Available intents: check_stock, get_price, list_skus, place_order, confirm, deny, escalate, end_call, unknown

SKU mapping (match loosely by name+size):
- AV-010 = Amla Hair Oil 180 ml
- AV-002 = Almond Hair Oil 100 ml
- AV-003 = Almond Hair Oil 200 ml

Distributor mapping:
- mumbai = DIST_MUM_01
- delhi  = DIST_DEL_01

Input: Mumbai wale ke paas amla hair oil 180 ml ka stock hai kya?"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=PROMPT,
    config=types.GenerateContentConfig(
        temperature=0,
        max_output_tokens=300,
        response_mime_type="application/json",
    ),
)

print("=== RAW response.text ===")
print(repr(response.text))
print("\n=== Candidates ===")
for i, c in enumerate(response.candidates):
    for j, p in enumerate(c.content.parts):
        print(f"  candidate[{i}].part[{j}]: type={type(p).__name__} text={repr(getattr(p, 'text', None))}")

print("\n=== Parsed ===")
try:
    print(json.loads(response.text))
except Exception as e:
    print(f"Parse failed: {e}")