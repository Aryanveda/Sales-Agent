import io
import logging
import os
import numpy as np
import soundfile as sf
import whisper
import librosa

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")

# Initial prompt steers Whisper to output Hinglish in Roman script
# instead of Devanagari Hindi — makes NLU matching far more reliable
HINGLISH_PROMPT = (
    "AryanVeda sales assistant conversation. "
    "Products: Amla Hair Oil, Almond Hair Oil, Coconut Oil, Boroneem Talcum, "
    "Fruit Glow Cream, Silk Plus Cold Cream, Nature Fresh Shampoo. "
    "Distributors: Mumbai, Delhi, Bangalore, Hyderabad, Punjab, Gujarat, Rajasthan. "
    "The speaker uses Hinglish — mix of Hindi and English in Roman script. "
    "Examples: 'mumbai wale ke paas amla hair oil 180 ml ka stock hai kya', "
    "'delhi distributor ko almond oil 100 ml ka price batao', "
    "'AV-010 ka stock check karo', "
    "'100 piece ka order place karna hai'. "
    "Always transcribe in Roman script Hinglish, never Devanagari."
)

class Transcriber:
    def __init__(self, model_size: str = "small"):
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info(f"Loading Whisper '{model_size}'...")
        self.model = whisper.load_model(model_size, download_root=MODEL_DIR)
        logger.info("Whisper ready.")

    def transcribe(self, audio_bytes: bytes) -> dict:
        if not audio_bytes:
            return {"text": "", "language": "hi", "confidence": 0.0}

        audio_array = self._bytes_to_array(audio_bytes)

        result = self.model.transcribe(
            audio_array,
            language="hi",           # tell Whisper the spoken language is Hindi
            task="transcribe",
            initial_prompt=HINGLISH_PROMPT,   # steer output to Roman script
            fp16=False,
            verbose=False,
        )

        text       = result.get("text", "").strip()
        language   = result.get("language", "hi")
        confidence = self._confidence(result)

        logger.info(f"[STT] '{text}' | conf={confidence:.2f}")
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