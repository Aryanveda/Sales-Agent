import io
import logging
import os
import numpy as np
import soundfile as sf
import whisper
import librosa

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")

# Long prompt full of Roman-script Hinglish examples forces Whisper.
# to output in Roman script even when speaker is talking Hindi.
# No hard mapping — just context examples that bias the output style.
HINGLISH_PROMPT = (
    "This is a sales call for AryanVeda herbal products. "
    "The caller speaks Hinglish — natural mix of Hindi words and English, always in Roman script. "
    "Example phrases from this call: "
    "'mumbai wale ke paas amla hair oil 180 ml ka stock hai kya', "
    "'bhai delhi mein almond oil kitne ka hai', "
    "'bangalore distributor ko 100 piece ka order dena hai', "
    "'kya coconut oil available hai gujarat mein', "
    "'price batao silk plus cold cream ka', "
    "'haan theek hai order place kar do', "
    "'nahi cancel kar do yaar', "
    "'kitna stock bacha hai pune mein', "
    "'AV-010 ka rate kya hai mumbai ke liye', "
    "'fruit glow cream 50 gram ka MRP kya hai', "
    "Transcribe exactly as spoken in Roman Hinglish script."
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
            language=None,              # auto-detect — avoids locking to Devanagari
            task="transcribe",
            initial_prompt=HINGLISH_PROMPT,
            fp16=False,
            verbose=False,
            condition_on_previous_text=True,   # uses prompt context throughout
        )

        text       = result.get("text", "").strip()
        language   = result.get("language", "hi")
        confidence = self._confidence(result)

        # Post-process: if Devanagari still slips through, flag it in logs
        devanagari_chars = sum(1 for c in text if '\u0900' <= c <= '\u097F')
        if devanagari_chars > 3:
            logger.warning(f"[STT] Devanagari detected in output ({devanagari_chars} chars) — NLU may still work via Gemini")

        logger.info(f"[STT] '{text}' | conf={confidence:.2f} | lang={language}")
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