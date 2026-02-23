import os
import json
import logging
from openai import OpenAI
from nlu.prompt import INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT

logger = logging.getLogger(__name__)


class IntentClassifier:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model  = model

    def classify(self, transcript: str) -> dict:
        """
        transcript : raw text from STT
        returns    : {
                       intent, confidence, entities, language
                     }
        """
        if not transcript.strip():
            return self._empty()

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                max_tokens=200,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                    {"role": "user",   "content": INTENT_USER_PROMPT.format(
                        transcript=transcript
                    )}
                ]
            )

            result = json.loads(response.choices[0].message.content)
            logger.info(f"[NLU] intent={result.get('intent')} conf={result.get('confidence')} lang={result.get('language')}")
            return result

        except Exception as e:
            logger.error(f"[NLU] failed: {e}")
            return self._empty()

    def _empty(self) -> dict:
        return {
            "intent":     "unknown",
            "confidence": 0.0,
            "entities": {
                "sku_code":        None,
                "distributor_name": None,
                "quantity":        None,
                "order_ref":       None
            },
            "language": "unknown"
        }