import io
import logging
import os
import numpy as np
import soundfile as sf
import whisper
import librosa

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")

HINGLISH_PROMPT = (
    "This is a sales call for AryanVeda/Nimson herbal products in India. "
    "The caller speaks Hinglish — natural mix of Hindi and English, always in Roman script. "
    "Example phrases: "
    "'colour plus shampoo 90 ml ka stock hai', "
    "'nimson amla hair oil 180 ml kitne ka hai', "
    "'kya coconut oil 500 ml available hai', "
    "'boroneem talcum powder price batao', "
    "'fruit glow cream 100 gram ka daam kya hai', "
    "'vasojelly mix 50 ml order karo', "
    "'nimson papaya d-tan face wash ka rate kya hai', "
    "'green apple shampoo 500 ml bhejna hai', "
    "'nimson herbal shampoo stock check karo', "
    "'aloevera cucumber cream 50 gram kitna hai', "
    "'hair removing cream 60 gram order dena hai', "
    "'gold bleach 43 gram available kya', "
    "'sunscreen spf 30 200 ml bhejo', "
    "'nimson lip guard 10 ml price', "
    "'keshsilk plus oil 450 ml chahiye', "
    "'divy cool cool oil 180 ml kitne piece chahiye', "
    "'nature fresh shampoo 500 ml daam', "
    "'olive body oil 100 ml order', "
    "'glycerin solution 110 ml stock', "
    "'gulab jal rose water 50 ml available', "
    "'charcoal face wash 60 ml', "
    "'ubtan face wash 100 ml', "
    "'vitamin c face wash 60 ml', "
    "'honey almond cream 100 gram', "
    "'hand body lotion 180 ml', "
    "'petroleum jelly 42 gram', "
    "'turmeric cream 30 gram order', "
    "Transcribe exactly as spoken in Roman Hinglish."
)


class Transcriber:
    def __init__(self, model_size: str = "small"):
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info(f"Loading Whisper '{model_size}'...")
        self.model = whisper.load_model(model_size, download_root=MODEL_DIR)
        logger.info("Whisper ready.")

    def transcribe(self, audio_bytes: bytes) -> dict:
        if not audio_bytes:
            return {"text": "", "language": "hinglish", "confidence": 0.0}

        audio_array = self._bytes_to_array(audio_bytes)

        result = self.model.transcribe(
            audio_array,
            language=None,
            task="transcribe",
            initial_prompt=HINGLISH_PROMPT,
            fp16=False,
            verbose=False,
            condition_on_previous_text=True,
        )

        text       = result.get("text", "").strip()
        language   = result.get("language", "hi")
        confidence = self._confidence(result)

        devanagari_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
        if devanagari_chars > 3:
            logger.warning(f"[STT] Devanagari detected ({devanagari_chars} chars) — NLU may still work")

        logger.info(f"[STT] text='{text}' confidence={confidence:.2f} language={language}")
        return {"text": text, "language": language, "confidence": confidence}

    def transcribe_file(self, path: str) -> dict:
        with open(path, "rb") as f:
            return self.transcribe(f.read())

    def _bytes_to_array(self, audio_bytes: bytes) -> np.ndarray:
        buf = io.BytesIO(audio_bytes)
        audio_array, sample_rate = sf.read(buf, dtype="float32")

        if audio_array.ndim == 2:
            audio_array = audio_array.mean(axis=1)

        if sample_rate != 16000:
            audio_array = librosa.resample(audio_array, orig_sr=sample_rate, target_sr=16000)

        return audio_array

    def _confidence(self, result: dict) -> float:
        segments = result.get("segments", [])
        if not segments:
            return 0.5
        avg_logprob = sum(s.get("avg_logprob", -1.0) for s in segments) / len(segments)
        return round(max(0.0, min(1.0, 1.0 + avg_logprob / 2.0)), 2)