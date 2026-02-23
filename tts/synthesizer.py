import io
import os
import logging
from tts.prompt import LLMResponse
from TTS.api import TTS
from gtts import gTTS
import gtts

logger = logging.getLogger(__name__)

MODEL_DIR    = os.path.join(os.path.dirname(__file__), "model")
VOICE_SAMPLE = os.path.join(os.path.dirname(__file__), "voice_samples", "voice.wav")

LLM_INTENTS = {"compare_skus", "recommend_product", "explain_product"}

TEMPLATES = {
    "check_stock": {
        "in_stock":       "{name} का स्टॉक {dist_name} के पास {stock_qty} {unit} उपलब्ध है।",
        "out_of_stock":   "{name} अभी {dist_name} के पास उपलब्ध नहीं है।",
        "no_sku":         "कृपया SKU code बताएं।",
        "no_distributor": "किस distributor का स्टॉक चेक करना है?",
    },
    "get_price": {
        "found":   "{name} की price {dist_name} के लिए ₹{price} प्रति {unit} है।",
        "no_data": "इस product की price जानकारी उपलब्ध नहीं है।",
        "no_sku":  "कौन से product की price चाहिए?",
    },
    "list_skus": {
        "found":   "{dist_name} के पास उपलब्ध products: {sku_list}।",
        "empty":   "{dist_name} के पास अभी कोई product उपलब्ध नहीं है।",
        "no_dist": "किस distributor की list चाहिए?",
    },
    "place_order": {
        "confirm": "क्या मैं {qty} {unit} {name} का order {dist_name} को place करूँ?",
        "success": "आपका order place हो गया। Order ID है {order_ref}।",
        "missing": "Order के लिए SKU code और quantity बताएं।",
    },
    "confirm":  {"default": "ठीक है, order place हो रहा है।"},
    "deny":     {"default": "कोई बात नहीं। कुछ और मदद चाहिए?"},
    "escalate": {"default": "मैं आपको हमारे executive से connect कर रहा हूँ।"},
    "end_call": {"default": "धन्यवाद! AryanVeda में call करने के लिए शुक्रिया।"},
    "unknown":  {"default": "माफ़ करें, मैं समझ नहीं पाया। दोबारा बोलें।"},
}


class ResponseBuilder:
    def __init__(self):
        self.llm = LLMResponse()

    def build(self, intent: str, sku_data: dict, entities: dict) -> str:
        if intent in LLM_INTENTS:
            return self.llm.generate(intent, sku_data, entities)
        response = self._rule_based(intent, sku_data, entities)
        if not response:
            return self.llm.generate(intent, sku_data, entities)
        return response

    def _rule_based(self, intent: str, data: dict, entities: dict) -> str:
        t = TEMPLATES.get(intent, {})

        if intent == "check_stock":
            if not entities.get("sku_code"):          return t["no_sku"]
            if not entities.get("distributor_code"):  return t["no_distributor"]
            if not data:                              return t["no_sku"]
            key = "in_stock" if data.get("stock_qty", 0) > 0 else "out_of_stock"
            return t[key].format(**data)

        elif intent == "get_price":
            if not entities.get("sku_code"): return t["no_sku"]
            if not data:                     return t["no_data"]
            return t["found"].format(**data)

        elif intent == "list_skus":
            if not entities.get("distributor_code"): return t["no_dist"]
            if not data.get("skus"):                 return t["empty"].format(**data)
            sku_list = ", ".join(s["name"] for s in data["skus"][:5])
            return t["found"].format(dist_name=data.get("dist_name", ""), sku_list=sku_list)

        elif intent == "place_order":
            if not data.get("order_ref") and not entities.get("sku_code"):
                return t["missing"]
            if data.get("order_ref"):
                return t["success"].format(**data)
            return t["confirm"].format(
                qty=entities.get("quantity", "?"),
                unit=data.get("unit", "units"),
                name=data.get("name", entities.get("sku_code", "")),
                dist_name=data.get("dist_name", "distributor"),
            )

        else:
            return t.get("default", "")


class Synthesizer:
    def __init__(self, model_path: str = None):
        os.makedirs(MODEL_DIR, exist_ok=True)
        self.voice_sample = VOICE_SAMPLE if os.path.exists(VOICE_SAMPLE) else None
        if self._is_windows():
            self._init_gtts()
        else:
            self._init_xtts(model_path)

    def _is_windows(self) -> bool:
        return os.name == "nt"

    def _init_gtts(self):
        self.engine = "gtts"
        logger.info("TTS engine: gTTS (Windows)")

    def _init_xtts(self, model_path: str = None):
        if model_path and os.path.exists(model_path):
            self.tts = TTS(model_path=model_path, progress_bar=False)
        else:
            self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False)
        self.engine = "xtts"
        logger.info("TTS engine: Coqui XTTS v2")

    def speak(self, text: str) -> bytes:
        if not text.strip():
            return b""
        try:
            if self.engine == "gtts":
                return self._speak_gtts(text)
            return self._speak_xtts(text)
        except Exception as e:
            logger.error(f"[TTS] failed: {e}")
            return b""

    def _speak_gtts(self, text: str) -> bytes:
        buf = io.BytesIO()
        gTTS(text=text, lang="hi").write_to_fp(buf)
        buf.seek(0)
        return buf.read()

    def _speak_xtts(self, text: str) -> bytes:
        buf = io.BytesIO()
        self.tts.tts_to_file(
            text=text,
            speaker_wav=self.voice_sample,
            language="hi",
            file_path=buf,
        )
        buf.seek(0)
        return buf.read()


class TTSPipeline:
    def __init__(self):
        self.builder     = ResponseBuilder()
        self.synthesizer = Synthesizer()

    def respond(self, intent: str, sku_data: dict, entities: dict) -> tuple[str, bytes]:
        text  = self.builder.build(intent, sku_data, entities)
        audio = self.synthesizer.speak(text)
        return text, audio