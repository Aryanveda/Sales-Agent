import io
import os
import logging
import subprocess
import tempfile
from tts.prompt import LLMResponse
from gtts import gTTS

logger = logging.getLogger(__name__)

# ── Voice sample path ─────────────────────────────────────────────────────────
# Your recorded voice sample — used for cloning
VOICE_SAMPLE = os.path.join(
    os.path.dirname(__file__),
    "..", "data", "recordings", "Tanmay.mp4"
)
# Converted WAV version (auto-generated on first run)
VOICE_WAV = os.path.join(
    os.path.dirname(__file__),
    "..", "data", "recordings", "Tanmay.wav"
)

LLM_INTENTS = {"compare_skus", "recommend_product", "explain_product"}

TEMPLATES = {
    "check_stock": {
        "in_stock":       "Haan bhai, {name} ka stock {dist_name} ke paas {stock_qty} {unit} available hai.",
        "out_of_stock":   "Yaar, {name} abhi {dist_name} ke paas available nahi hai.",
        "no_sku":         "Bhai, konsa SKU code chahiye? Zara batao.",
        "no_distributor": "Kis distributor ka stock check karna hai? Naam batao.",
    },
    "get_price": {
        "found":   "Haan, {name} ki price {dist_name} ke liye rupaye {price} per {unit} hai.",
        "no_data": "Bhai, is product ki price abhi available nahi hai.",
        "no_sku":  "Konse product ki price chahiye? SKU batao.",
    },
    "list_skus": {
        "found":   "{dist_name} ke paas ye products available hain: {sku_list}.",
        "empty":   "Yaar, {dist_name} ke paas abhi koi product available nahi hai.",
        "no_dist": "Kis distributor ki list chahiye bhai?",
    },
    "place_order": {
        "confirm": "Bhai, kya main {qty} {unit} {name} ka order {dist_name} ko place karun?",
        "success": "Done bhai! Order place ho gaya. Order ID hai {order_ref}.",
        "missing": "Yaar, SKU code aur quantity batao tabhi order place hoga.",
    },
    "confirm":  {"default": "Theek hai bhai, order place ho raha hai."},
    "deny":     {"default": "Koi baat nahi. Kuch aur kaam ho toh batao."},
    "escalate": {"default": "Ek second bhai, main tumhe apne executive se connect karta hun."},
    "end_call": {"default": "Theek hai bhai, koi kaam ho toh call karna. AryanVeda mein call karne ka shukriya!"},
    "unknown":  {"default": "Yaar, samajh nahi aaya. Ek baar phir se bolo."},
}


def _convert_mp4_to_wav(mp4_path: str, wav_path: str):
    """Convert MP4 voice sample to WAV using ffmpeg (required by Coqui TTS)."""
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", mp4_path,
            "-ar", "22050",
            "-ac", "1",
            "-f", "wav",
            wav_path
        ], check=True, capture_output=True)
        logger.info(f"[TTS] Converted voice sample to WAV: {wav_path}")
        return True
    except Exception as e:
        logger.error(f"[TTS] ffmpeg conversion failed: {e}")
        return False


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
            if not entities.get("sku_code"):         return t["no_sku"]
            if not entities.get("distributor_code"): return t["no_distributor"]
            if not data:                             return t["no_sku"]
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
    def __init__(self):
        self.voice_wav  = os.path.abspath(VOICE_WAV)
        self.voice_mp4  = os.path.abspath(VOICE_SAMPLE)
        self.tts_model  = None
        self._init_engine()

    def _init_engine(self):
        """Try to load Coqui TTS with voice cloning. Fall back to gTTS if unavailable."""
        # Ensure WAV sample exists
        if not os.path.exists(self.voice_wav):
            if os.path.exists(self.voice_mp4):
                _convert_mp4_to_wav(self.voice_mp4, self.voice_wav)
            else:
                logger.warning(f"[TTS] Voice sample not found at {self.voice_mp4}")

        try:
            from TTS.api import TTS
            # XTTS-v2: best multilingual voice cloning model, supports Hindi + Hinglish
            self.tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
            logger.info("[TTS] Engine: Coqui XTTS-v2 (your voice clone)")
            self.engine = "coqui"
        except Exception as e:
            logger.warning(f"[TTS] Coqui TTS not available ({e}), falling back to gTTS")
            self.engine = "gtts"

    def speak(self, text: str) -> bytes:
        if not text.strip():
            return b""
        try:
            if self.engine == "coqui" and os.path.exists(self.voice_wav):
                return self._speak_coqui(text)
            return self._speak_gtts(text)
        except Exception as e:
            logger.error(f"[TTS] speak failed: {e}, falling back to gTTS")
            return self._speak_gtts(text)

    def _speak_coqui(self, text: str) -> bytes:
        """Generate speech in your cloned voice using Coqui XTTS-v2."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
        try:
            self.tts_model.tts_to_file(
                text=text,
                speaker_wav=self.voice_wav,
                language="hi",          # Hindi/Hinglish
                file_path=out_path,
            )
            with open(out_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def _speak_gtts(self, text: str) -> bytes:
        """Fallback: gTTS generic Hindi voice."""
        buf = io.BytesIO()
        gTTS(text=text, lang="hi").write_to_fp(buf)
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