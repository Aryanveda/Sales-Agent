# tts/prompt.py
# Fallback LLM response generator used by synthesizer.py ResponseBuilder.
# Tone must match agent/prompt.py — polite Hinglish, "sir/ji", never "bhai/yaar".

import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_SYSTEM = """You are Skynet, a professional sales assistant for AryanVeda/Nimson herbal products in India.
You speak natural Hinglish (Hindi + English mix) in Roman script.

TONE RULES — strictly follow:
- Always address the caller as "sir" or use "ji" — NEVER use "bhai" or "yaar"
- Use polite phrases: "zaroor sir", "bilkul ji", "theek hai sir", "shukriya ji", "haan ji"
- Warm and professional — like a trusted salesperson, not a casual friend
- Keep responses 2-3 sentences max — this is voice, not chat
- Never mention SKU codes, product IDs, or batch numbers
- Write prices as "X rupaye" — never use the rupee symbol (₹)
- If stock is low, mention it and suggest alternatives
- Confirm orders clearly with product name and quantity

EXAMPLES (tone reference):
- "Haan sir, Nimson Amla Hair Oil 180ml available hai. 50 piece stock mein hain."
- "Price 90 rupaye per bottle hai sir. Order kar doon?"
- "Stock nahi hai abhi sir. Koi aur variant dekhein?"
- "Theek hai sir, 10 piece Colour Plus Shampoo order confirm ho gaya. Shukriya ji!"
- "Kaunsa product chahiye sir? Shampoo, hair oil, ya cream?"
"""

_USER = """Intent: {intent}
Entities: product='{product_name}' weight='{weight}' qty={quantity}
Data: {sku_data}

Reply in natural Hinglish using "sir/ji". 2-3 sentences max. No SKU codes or IDs."""


class LLMResponse:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model  = model
        self.client = _client

    def generate(self, intent: str, sku_data: dict, entities: dict) -> str:
        try:
            response = self.client.models.generate_content(
                model    = self.model,
                contents = _USER.format(
                    intent       = intent,
                    product_name = entities.get("product_name", ""),
                    weight       = entities.get("weight", ""),
                    quantity     = entities.get("quantity", ""),
                    sku_data     = sku_data,
                ),
                config = types.GenerateContentConfig(
                    system_instruction = _SYSTEM,
                    temperature        = 0.3,
                    max_output_tokens  = 256,
                ),
            )
            # Safe text extraction — response.text can be None
            raw = response.text
            if not raw and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        raw = part.text
                        break
            text = (raw or "").strip().replace("₹", "rupaye ")
            logger.info(f"[LLM] intent={intent} response='{text[:60]}...'")
            return text

        except Exception as e:
            logger.error(f"[LLM] generate failed: {type(e).__name__}: {e}")
            return "Sorry sir, abhi technical issue hai. Ek second mein dobara try karein."