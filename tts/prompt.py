import os
import logging
from google import genai
from google.genai import types

logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

_SYSTEM = """You are Skynet, AryanVeda's friendly sales assistant on a phone call.
- Speak natural Hinglish (Hindi + English mix the way Indian salespeople talk)
- Never say SKU codes, batch numbers, or internal IDs
- Use "bhai", "ji", "yaar" naturally
- Keep responses to 2-3 sentences — this is voice, not chat
- Be warm and proactive — mention low stock urgency, suggest alternatives"""

_USER = """Intent: {intent}
DB data: {sku_data}
Entities: {entities}

Reply as Skynet in natural Hinglish. 2-3 sentences max. No SKU codes."""


class LLMResponse:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model  = model
        self.client = _client

    def generate(self, intent: str, sku_data: dict, entities: dict) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=_USER.format(
                    intent=intent,
                    sku_data=sku_data,
                    entities=entities,
                ),
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    temperature=0.4,
                    max_output_tokens=2000,   # was 120 — caused all truncation
                ),
            )
            text = response.text.strip()
            logger.info(f"[LLM] '{text}'")
            return text

        except Exception as e:
            logger.error(f"[LLM] failed: {e}")
            return "Sorry bhai, abhi kuch technical issue hai. Ek second mein dobara try karo."