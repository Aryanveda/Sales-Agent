"""
agent/order_extractor.py
Runs at end of every call where place_order intent was detected.
Parses the full transcript via Gemini and returns structured order data.
"""

import json
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

IST = timezone(timedelta(hours=5, minutes=30))

_SYSTEM = """You are an order extraction assistant for AryanVeda/Nimson herbal products.
Extract all confirmed product orders from a sales call transcript.
Only include items the customer explicitly confirmed or agreed to order.
Ignore products that were inquired about but not ordered.
Return ONLY valid JSON, no preamble, no markdown."""

_PROMPT = """Extract all confirmed orders from this sales call transcript.

Transcript:
{transcript}

Caller info:
- Phone: {phone}
- Name: {caller_name}
- Type: {customer_type}

Return a JSON object:
{{
  "has_order": true/false,
  "caller_confirmed": true/false,
  "notes": "any special instructions or notes from the call",
  "items": [
    {{
      "product_name": "exact product name",
      "weight": "e.g. 100ml, 200g, 500ml",
      "quantity": 10,
      "unit_price": 45.0,
      "total_price": 450.0,
      "confirmed": true
    }}
  ]
}}

If no order was confirmed, return {{"has_order": false, "items": []}}."""


class OrderExtractor:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model  = model
        self.client = _client

    def extract(
        self,
        transcript_turns: List[Dict],
        phone: str = "unknown",
        caller_name: str = "",
        customer_type: str = "unknown",
    ) -> Optional[Dict]:
        """
        transcript_turns: list of {"role": "caller"|"agent", "text": "...", "turn": N}
        Returns order dict or None if no order found.
        """
        if not transcript_turns:
            return None

        full_text = "\n".join(
            f"[{t['role'].upper()} turn {t['turn']}]: {t['text']}"
            for t in transcript_turns
        )

        prompt = _PROMPT.format(
            transcript    = full_text,
            phone         = phone,
            caller_name   = caller_name or "Unknown",
            customer_type = customer_type,
        )

        try:
            resp = self.client.models.generate_content(
                model    = self.model,
                contents = prompt,
                config   = types.GenerateContentConfig(
                    system_instruction = _SYSTEM,
                    temperature        = 0.1,
                    max_output_tokens  = 800,
                    response_mime_type = "application/json",
                ),
            )
            raw = (getattr(resp, "text", "") or "").strip()
            # strip json fences if present
            raw = raw.replace("```json", "").replace("```", "").strip()

            result = json.loads(raw)

            if not result.get("has_order"):
                logger.info(f"[OrderExtractor] No confirmed order for {phone}")
                return None

            items = [i for i in result.get("items", []) if i.get("confirmed")]
            if not items:
                return None

            result["items"]         = items
            result["phone"]         = phone
            result["caller_name"]   = caller_name
            result["customer_type"] = customer_type
            result["extracted_at"]  = datetime.now(IST).isoformat()

            logger.info(f"[OrderExtractor] {len(items)} item(s) for {phone}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[OrderExtractor] JSON parse failed: {e} | raw={raw[:200]}")
            return None
        except Exception as e:
            logger.error(f"[OrderExtractor] Failed: {e}")
            return None

    def has_order_intent(self, intent_history: List[str]) -> bool:
        """Quick check — don't run extractor if no order intent appeared."""
        order_intents = {"place_order", "confirm_order", "order_product", "buy_product"}
        return bool(order_intents.intersection(set(intent_history)))