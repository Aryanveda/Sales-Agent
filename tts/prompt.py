import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are AryanVeda's Hindi voice sales assistant.
You help distributors check SKU stock, pricing, and place orders.

Rules:
- Always respond in Hindi only
- Be concise — max 2 sentences (this is a spoken response, not written)
- Use natural conversational Hindi, not formal
- Never make up stock numbers or prices — if data is missing, say so
- Address the distributor respectfully"""


USER_PROMPT = """Intent detected: {intent}

SKU data from database:
{sku_data}

Entities extracted from caller speech:
{entities}

Generate a natural Hindi voice response for this situation."""


class LLMResponse:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model  = model

    def generate(self, intent: str, sku_data: dict, entities: dict) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.3,
                max_tokens=120,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": USER_PROMPT.format(
                            intent=intent,
                            sku_data=sku_data,
                            entities=entities,
                        )
                    },
                ]
            )
            text = response.choices[0].message.content.strip()
            logger.info(f"[LLM] '{text}'")
            return text

        except Exception as e:
            logger.error(f"[LLM] failed: {e}")
            return "माफ़ करें, अभी जानकारी उपलब्ध नहीं है। कृपया दोबारा कोशिश करें।"