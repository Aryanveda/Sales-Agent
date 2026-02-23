import os
import re
import json
import logging
import psycopg2
import psycopg2.extras
from openai import OpenAI
from nlu.prompt import ENTITY_SYSTEM_PROMPT, ENTITY_USER_PROMPT

logger = logging.getLogger(__name__)


class EntityResolver:
    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model  = model
        self.db     = self._connect_db()

    def _connect_db(self):
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", 5432),
            dbname=os.getenv("DB_NAME", "aryaveda"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
        )

    def _fetch_distributors(self) -> list:
        """Pull distributor list fresh from DB each time."""
        with self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT code, name, name_hindi
                FROM distributors
                WHERE is_active = TRUE
                ORDER BY name
            """)
            return [dict(r) for r in cur.fetchall()]

    def resolve(self, raw_entities: dict) -> dict:
        resolved = {
            "sku_code":         self._resolve_sku(raw_entities.get("sku_code")),
            "distributor_code": self._resolve_distributor(raw_entities.get("distributor_name")),
            "quantity":         raw_entities.get("quantity"),
            "order_ref":        raw_entities.get("order_ref"),
        }
        logger.info(f"[Entities] resolved: {resolved}")
        return resolved

    def _resolve_sku(self, raw_sku: str) -> str | None:
        if not raw_sku:
            return None
        cleaned = raw_sku.upper().strip()
        if re.match(r'^AV\d+$', cleaned):
            cleaned = cleaned[:2] + "-" + cleaned[2:]
        return cleaned

    def _resolve_distributor(self, spoken_name: str) -> str | None:
        if not spoken_name:
            return None

        distributors = self._fetch_distributors()

        # Quick case-insensitive name match before calling GPT
        spoken_lower = spoken_name.lower().strip()
        for dist in distributors:
            if spoken_lower in dist["name"].lower() or spoken_lower in (dist.get("name_hindi") or "").lower():
                logger.info(f"[Entities] direct name match: {dist['code']}")
                return dist["code"]

        # GPT fuzzy match against live DB list
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                max_tokens=100,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": ENTITY_SYSTEM_PROMPT.format(
                            distributor_list=json.dumps(distributors, ensure_ascii=False, indent=2)
                        )
                    },
                    {
                        "role": "user",
                        "content": ENTITY_USER_PROMPT.format(spoken_name=spoken_name)
                    }
                ]
            )

            result = json.loads(response.choices[0].message.content)
            code   = result.get("distributor_code")
            conf   = result.get("confidence", 0)

            if code and conf >= 0.7:
                logger.info(f"[Entities] GPT match: {code} conf={conf}")
                return code

            logger.warning(f"[Entities] low confidence: {result}")
            return None

        except Exception as e:
            logger.error(f"[Entities] distributor resolution failed: {e}")
            return None