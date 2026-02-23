import io
import logging
import os
import numpy as np
import soundfile as sf
import whisper
import librosa

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")


class Transcriber:
    def __init__(self, model_size: str = "medium"):
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
            language="hi",
            task="transcribe",
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