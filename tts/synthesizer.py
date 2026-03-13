import io
import os
import logging
import subprocess
import tempfile
from tts.prompt import LLMResponse
from gtts import gTTS

logger = logging.getLogger(__name__)

VOICE_SAMPLE = os.path.join(
    os.path.dirname(__file__),
    "..", "data", "recordings", "Tanmay.mp4"
)

VOICE_WAV = os.path.join(
    os.path.dirname(__file__),
    "..", "data", "recordings", "Tanmay.wav"
)

TEMPLATES = {
    "check_stock": {
        "in_stock": "Haan bhai, {product_name} {weight} available hai. Stock mein {stock_qty} piece hain.",
        "out_of_stock": "Yaar, {product_name} {weight} abhi available nahi hai.",
        "clarify": "Bhai, kaunsa product aur weight chahiye? Zara detail mein batao.",
    },
    "get_price": {
        "found": "{product_name} {weight} ka MRP rupaye {mrp_unit} hai. Retail price {retail} rupay.",
        "no_data": "Bhai, is product ki price abhi available nahi hai.",
        "clarify": "Kaunse product ki price chahiye? Naam batao.",
    },
    "list_skus": {
        "default": "Hamare paas shampoo, hair oil, talcum powder, creams, face wash aur bahut sare products hain. Kaunsa product chahiye?",
    },
    "place_order": {
        "confirm": "Bhai, kya main {quantity} piece {product_name} {weight} ka order confirm karun?",
        "success": "Bilkul! {quantity} piece {product_name} order confirm ho gaya.",
        "clarify": "Bhai, product aur quantity dono batao to order kar du.",
    },
    "confirm": {
        "default": "Theek hai bhai, order process ho raha hai.",
    },
    "deny": {
        "default": "Koi baat nahi. Aur kuch chahiye to batao.",
    },
    "escalate": {
        "default": "Ek second bhai, manager ko bulata hun. Thoda wait karo.",
    },
    "end_call": {
        "default": "Theek hai bhai! AryanVeda mein call karne ke liye shukriya. Aur kaam ho to fir call karna.",
    },
    "unknown": {
        "default": "Yaar, samajh nahi aaya. Ek baar phir se bolo kya chahiye?",
    },
}


def _convert_mp4_to_wav(mp4_path: str, wav_path: str) -> bool:
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", mp4_path,
            "-ar", "22050", "-ac", "1", "-f", "wav", wav_path
        ], check=True, capture_output=True)
        logger.info(f"[TTS] Voice sample converted to WAV: {wav_path}")
        return True
    except Exception as e:
        logger.error(f"[TTS] ffmpeg conversion failed: {e}")
        return False


class ResponseBuilder:
    def __init__(self):
        self.llm = LLMResponse()

    def build(self, intent: str, sku_data: dict, entities: dict) -> str:
        templates = TEMPLATES.get(intent, {})
        
        if intent == "check_stock":
            if not sku_data:
                return templates.get("clarify", "Kaunsa product ka stock check karna hai?")
            stock = sku_data.get("stock_qty", 0)
            key = "in_stock" if stock > 0 else "out_of_stock"
            try:
                return templates[key].format(
                    product_name=sku_data.get("product_name", ""),
                    weight=sku_data.get("weight", ""),
                    stock_qty=stock
                )
            except KeyError:
                return self.llm.generate(intent, sku_data, entities)

        elif intent == "get_price":
            if not sku_data:
                return templates.get("clarify", "Kaunse product ka price dekhna hai?")
            mrp = sku_data.get("mrp_unit")
            if mrp:
                try:
                    return templates["found"].format(
                        product_name=sku_data.get("product_name", ""),
                        weight=sku_data.get("weight", ""),
                        mrp_unit=mrp,
                        retail=sku_data.get("retail", mrp)
                    )
                except KeyError:
                    return self.llm.generate(intent, sku_data, entities)
            return templates.get("no_data", "Price abhi available nahi hai.")

        elif intent == "place_order":
            if not sku_data or not entities.get("quantity"):
                return templates.get("clarify", "Product aur quantity batao.")
            if entities.get("order_ref"):
                try:
                    return templates["success"].format(
                        quantity=entities.get("quantity", ""),
                        product_name=sku_data.get("product_name", ""),
                        weight=sku_data.get("weight", "")
                    )
                except KeyError:
                    return self.llm.generate(intent, sku_data, entities)
            try:
                return templates["confirm"].format(
                    quantity=entities.get("quantity", ""),
                    product_name=sku_data.get("product_name", ""),
                    weight=sku_data.get("weight", "")
                )
            except KeyError:
                return self.llm.generate(intent, sku_data, entities)

        elif intent in ["list_skus", "confirm", "deny", "escalate", "end_call", "unknown"]:
            return templates.get("default", "")

        else:
            return self.llm.generate(intent, sku_data, entities)


class Synthesizer:
    def __init__(self):
        self.voice_wav = os.path.abspath(VOICE_WAV)
        self.voice_mp4 = os.path.abspath(VOICE_SAMPLE)
        self.tts_model = None
        self.engine = None
        self._init_engine()

    def _init_engine(self):
        if not os.path.exists(self.voice_wav):
            if os.path.exists(self.voice_mp4):
                _convert_mp4_to_wav(self.voice_mp4, self.voice_wav)
            else:
                logger.warning(f"[TTS] Voice sample not found: {self.voice_mp4}")

        try:
            from TTS.api import TTS
            self.tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
            self.engine = "coqui"
            logger.info("[TTS] Engine: Coqui XTTS-v2")
        except Exception as e:
            logger.warning(f"[TTS] Coqui not available: {e} → using gTTS")
            self.engine = "gtts"

    def speak(self, text: str) -> bytes:
        if not text or not text.strip():
            return b""

        try:
            if self.engine == "coqui" and self.tts_model and os.path.exists(self.voice_wav):
                return self._speak_coqui(text)
            return self._speak_gtts(text)
        except Exception as e:
            logger.error(f"[TTS] speak failed: {e} → falling back to gTTS")
            return self._speak_gtts(text)

    def _speak_coqui(self, text: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name

        try:
            self.tts_model.tts_to_file(
                text=text,
                speaker_wav=self.voice_wav,
                language="hi",
                file_path=out_path,
            )
            with open(out_path, "rb") as f:
                audio = f.read()
            logger.info(f"[TTS] Generated audio ({len(audio)} bytes) via Coqui")
            return audio
        except Exception as e:
            logger.error(f"[TTS] Coqui generation failed: {e}")
            return b""
        finally:
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except:
                    pass

    def _speak_gtts(self, text: str) -> bytes:
        try:
            buf = io.BytesIO()
            gTTS(text=text, lang="hi", slow=False).write_to_fp(buf)
            buf.seek(0)
            audio = buf.read()
            logger.info(f"[TTS] Generated audio ({len(audio)} bytes) via gTTS")
            return audio
        except Exception as e:
            logger.error(f"[TTS] gTTS generation failed: {e}")
            return b""


class TTSPipeline:
    def __init__(self):
        self.builder = ResponseBuilder()
        self.synthesizer = Synthesizer()

    def respond(self, intent: str, sku_data: dict, entities: dict) -> tuple[str, bytes]:
        text = self.builder.build(intent, sku_data, entities)
        audio = self.synthesizer.speak(text)
        logger.info(f"[TTSPipeline] intent={intent} text_len={len(text)} audio_len={len(audio)}")
        return text, audio