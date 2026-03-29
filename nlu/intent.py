import os
import json
import logging
import time
from google import genai
from google.genai import types
from google.genai.errors import ServerError

try:
    from httpx import RemoteProtocolError as _RemoteProtocolError
except ImportError:
    _RemoteProtocolError = ConnectionError

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

from agent.prompt import INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT

logger  = logging.getLogger(__name__)
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

HISTORY_WINDOW = 20


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
        self.model   = model
        self.client  = _client
        self._history: list[dict] = []

    def classify(self, transcript: str, retries: int = 3, backoff: float = 2.0) -> dict:
        if not transcript.strip():
            return self._empty()

        self._history.append({"role": "caller", "text": transcript.strip()})
        prompt = self._build_prompt(transcript)

        for attempt in range(1, retries + 1):
            try:
                response = self.client.models.generate_content(
                    model    = self.model,
                    contents = prompt,
                    config   = types.GenerateContentConfig(
                        system_instruction = INTENT_SYSTEM_PROMPT,
                        temperature        = 1,
                        max_output_tokens  = 150,
                        thinking_config    = types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                result   = _extract_json(_extract_text(response))
                entities = result.get("entities", {})
                logger.info(
                    f"[NLU] intent={result.get('intent')} conf={result.get('confidence')} "
                    f"product='{entities.get('product_name')}' "
                    f"weight='{entities.get('weight_hint')}' qty={entities.get('quantity')}"
                )
                return result

            except (ServerError, _RemoteProtocolError, ConnectionError):
                if attempt < retries:
                    logger.warning(f"[NLU] Connection error, retry {attempt}/{retries}")
                    time.sleep(backoff * attempt)
                else:
                    logger.error(f"[NLU] Failed after {retries} attempts")
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

    def _build_prompt(self, transcript: str) -> str:
        recent = self._history[-HISTORY_WINDOW:]
        lines  = ["=== CONVERSATION HISTORY ==="]
        for turn in recent:
            tag = "[caller]" if turn["role"] == "caller" else "[agent] "
            lines.append(f"{tag}: {turn['text']}")
        lines.append("")
        lines.append(INTENT_USER_PROMPT.format(transcript=transcript))
        return "\n".join(lines)

    def _empty(self) -> dict:
        return {
            "intent":     "unknown",
            "confidence": 0.0,
            "entities":   {"product_name": None, "weight_hint": None, "quantity": None, "order_ref": None},
            "language":   "hinglish",
        }

# ── Response cache ────────────────────────────────────────────────────────────
# Required by agent/skynet.py — caches get_price/check_stock responses for 90s
# so repeated queries for the same product skip the full LLM call (~300ms saved)

import hashlib
from typing import Optional, Dict


class ResponseCache:
    def __init__(self, ttl: int = 90, max_size: int = 200):
        self._cache: Dict[str, dict] = {}
        self._times: Dict[str, float] = {}
        self.ttl      = ttl
        self.max_size = max_size

    def _key(self, intent: str, product_id: Optional[str],
             weight: Optional[str], customer_type: Optional[str]) -> str:
        raw = f"{intent}|{product_id or ''}|{weight or ''}|{customer_type or ''}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, intent: str, product_id: Optional[str],
            weight: Optional[str], customer_type: Optional[str]) -> Optional[dict]:
        if intent not in ("get_price", "check_stock") or not product_id:
            return None
        k = self._key(intent, product_id, weight, customer_type)
        if k in self._cache:
            if time.time() - self._times[k] < self.ttl:
                logger.info(f"[Cache] HIT intent={intent} product={product_id}")
                return self._cache[k]
            del self._cache[k]
            del self._times[k]
        return None

    def set(self, intent: str, product_id: Optional[str],
            weight: Optional[str], customer_type: Optional[str], response: dict):
        if intent not in ("get_price", "check_stock") or not product_id:
            return
        if len(self._cache) >= self.max_size:
            oldest = min(self._times, key=self._times.get)
            del self._cache[oldest]
            del self._times[oldest]
        k = self._key(intent, product_id, weight, customer_type)
        self._cache[k] = response
        self._times[k] = time.time()


_response_cache = ResponseCache()


def get_response_cache() -> ResponseCache:
    return _response_cache