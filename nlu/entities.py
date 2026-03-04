import os
import re
import json
import logging
import sqlite3
from google import genai
from google.genai import types
from nlu.prompt import ENTITY_SYSTEM_PROMPT, ENTITY_USER_PROMPT

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv()

logger  = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "db/aryaveda.db")
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _parse_json(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("Empty response from model")
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned.strip())


def _extract_text(response) -> str:
    raw = response.text if response.text else ""
    if not raw and response.candidates:
        raw = "".join(
            part.text
            for part in response.candidates[0].content.parts
            if hasattr(part, "text") and part.text
        )
    return raw


class EntityResolver:
    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model   = model
        self.client  = _client
        self.db_path = DB_PATH

    def _fetch_distributors(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT code, name, name_hindi FROM distributors WHERE is_active = 1"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def resolve(self, raw_entities: dict) -> dict:
        resolved = {
            "sku_code":         self._resolve_sku(raw_entities.get("sku_code")),
            "distributor_code": self._resolve_distributor(raw_entities.get("distributor_name")),
            "quantity":         raw_entities.get("quantity"),
            "order_ref":        raw_entities.get("order_ref"),
        }
        logger.info(f"[Entities] resolved: {resolved}")
        return resolved

    def _resolve_sku(self, raw_sku):
        if not raw_sku:
            return None
        cleaned = raw_sku.upper().strip()
        if re.match(r'^AV\d+$', cleaned):
            cleaned = cleaned[:2] + "-" + cleaned[2:]
        return cleaned

    def _resolve_distributor(self, spoken_name):
        if not spoken_name:
            return None

        distributors = self._fetch_distributors()
        spoken_lower = spoken_name.lower().strip()

        for dist in distributors:
            if spoken_lower in dist["name"].lower() or spoken_lower in (dist.get("name_hindi") or "").lower():
                logger.info(f"[Entities] direct match: {dist['code']}")
                return dist["code"]

        try:
            system_prompt = ENTITY_SYSTEM_PROMPT.format(
                distributor_list=json.dumps(distributors, ensure_ascii=False, indent=2)
            )
            prompt   = ENTITY_USER_PROMPT.format(spoken_name=spoken_name)
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0,
                    max_output_tokens=100,
                    response_mime_type="application/json",
                ),
            )
            result = _parse_json(_extract_text(response))
            code   = result.get("distributor_code")
            conf   = result.get("confidence", 0)
            if code and conf >= 0.7:
                logger.info(f"[Entities] Gemini match: {code} conf={conf}")
                return code
            return None
        except Exception as e:
            logger.error(f"[Entities] failed: {e}")
            return None