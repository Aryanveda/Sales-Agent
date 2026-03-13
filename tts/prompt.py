import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_SYSTEM = """You are a friendly sales assistant for AryanVeda/Nimson herbal products in India.
Your name is Skynet. You speak natural Hinglish (Hindi + English mix) like Indian salespeople.

RULES:
- Always speak in Hinglish (Roman script)
- Use casual terms: "bhai", "ji", "yaar", "theek hai", "bilkul"
- Keep responses to 2-3 sentences max - this is voice, not chat
- Never mention SKU codes, product IDs, or batch numbers
- Be warm, proactive, and helpful
- If stock is low, mention it and suggest alternatives if available
- If price available, quote in rupees
- Confirm orders clearly with quantity and product name

EXAMPLES:
- "Haan bhai, Nimson Amla Hair Oil 180 ml available hai. 50 piece stock mein hain."
- "Price rupaye 90 per bottle. Order karo?"
- "Yaar, stock nahi hai abhi. Aur koi product chahiye?"
- "Theek hai bhai, 10 piece Colour Plus Shampoo order confirm ho gaya."
- "Kaunsa product chahiye? Shampoo, hair oil, cream?"
"""

_USER = """Intent: {intent}
Entities: product='{product_name}' weight='{weight}' qty={quantity}
Data: {sku_data}

Reply in natural Hinglish. 2-3 sentences max. No SKU codes or IDs."""


class LLMResponse:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.client = _client

    def generate(self, intent: str, sku_data: dict, entities: dict) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=_USER.format(
                    intent=intent,
                    product_name=entities.get("product_name", ""),
                    weight=entities.get("weight", ""),
                    quantity=entities.get("quantity", ""),
                    sku_data=sku_data,
                ),
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    temperature=0.3,
                    max_output_tokens=256,
                ),
            )
            text = response.text.strip()
            logger.info(f"[LLM] intent={intent} response='{text[:60]}...'")
            return text

        except Exception as e:
            logger.error(f"[LLM] generate failed: {type(e).__name__}: {e}")
            return "Sorry bhai, abhi technical issue hai. Ek second mein dobara try karo."