import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


SYSTEM_PROMPT = """You are AryanVeda's Hinglish voice sales assistant.
You help distributors check SKU stock, pricing, and place orders.

Rules:
- Always respond in Hinglish (natural mix of Hindi and English — the way people actually speak in Indian business)
- Example style: "Haan bhai, AV-101 ka stock abhi 200 units available hai Mumbai warehouse mein."
- Be concise — max 2 sentences (this is a spoken voice response, not written)
- Never make up stock numbers or prices — if data is missing, say so clearly
- Address the distributor in a friendly, respectful tone
- Use English for product names, SKU codes, numbers, and business terms
- Use Hindi for conversational connectors and natural flow"""


USER_PROMPT = """Intent detected: {intent}

SKU data from database:
{sku_data}

Entities extracted from caller speech:
{entities}

Generate a natural Hinglish voice response for this situation."""


class LLMResponse:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model  = model
        self.client = _client

    def generate(self, intent: str, sku_data: dict, entities: dict) -> str:
        try:
            prompt = USER_PROMPT.format(
                intent=intent,
                sku_data=sku_data,
                entities=entities,
            )
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=120,
                ),
            )
            text = response.text.strip()
            logger.info(f"[LLM] '{text}'")
            return text

        except Exception as e:
            logger.error(f"[LLM] failed: {e}")
            return "Sorry bhai, abhi information available nahi hai. Please thodi der baad try karein."