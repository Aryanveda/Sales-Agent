import io
import logging
import os
import numpy as np
import soundfile as sf
import whisper
import librosa

logger = logging.getLogger(__name__)

MODEL_DIR  = os.path.join(os.path.dirname(__file__), "model")
MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")

HINGLISH_PROMPT = (
    "Hinglish sales call transcript in Roman script. "
    "Hindi words written in English letters only, never Devanagari. "
    "mujhe amla hair oil ke baare mein jaanna tha, "
    "colour plus shampoo 90 ml ka stock hai kya sir, "
    "nimson almond hair oil 200 ml ka price kya hai, "
    "kya coconut oil 500 ml available hai, "
    "boroneem talcum powder ka rate batao sir, "
    "fruit glow cream 100 gram ka daam kya hai, "
    "vasojelly mix 50 ml order karna tha, "
    "green apple shampoo 500 ml chahiye, "
    "hair removing cream 60 gram order dena hai, "
    "keshsilk plus oil 450 ml chahiye sir, "
    "haan sir theek hai bilkul, "
    "price batao sir stock check karo, "
    "order confirm kar do, "
    "nahi chahiye cancel kar do, "
    "manager se baat karni hai, "
    "shukriya ji bye."
)

_DECODE_KWARGS = dict(
    language                    = "en",
    task                        = "transcribe",
    initial_prompt              = HINGLISH_PROMPT,
    fp16                        = False,
    verbose                     = False,
    condition_on_previous_text  = True,
    no_speech_threshold         = 0.4,
    logprob_threshold           = -1.0,
    compression_ratio_threshold = 2.4,
)


class Transcriber:
    def __init__(self, model_size: str = MODEL_SIZE):
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info(f"[STT] Loading Whisper '{model_size}'...")
        self.model      = whisper.load_model(model_size, download_root=MODEL_DIR)
        self._prev_text = ""
        logger.info("[STT] Whisper ready.")

    def transcribe(self, audio_bytes: bytes) -> dict:
        if not audio_bytes:
            return {"text": "", "language": "hinglish", "confidence": 0.0}
        audio  = self._to_array(audio_bytes)
        result = self.model.transcribe(audio, **_DECODE_KWARGS)
        text   = self._sanitise(result.get("text", ""))
        conf   = self._confidence(result)
        logger.info(f"[STT] '{text}' conf={conf:.2f}")
        return {"text": text, "language": "hinglish", "confidence": conf}

    def transcribe_stream(self, audio_bytes: bytes) -> dict:
        if not audio_bytes:
            return {"text": "", "language": "hinglish", "confidence": 0.0}
        audio         = self._to_array(audio_bytes)
        prompt        = HINGLISH_PROMPT + (" " + self._prev_text[-200:] if self._prev_text else "")
        kwargs        = {**_DECODE_KWARGS, "initial_prompt": prompt}
        result        = self.model.transcribe(audio, **kwargs)
        text          = self._sanitise(result.get("text", ""))
        conf          = self._confidence(result)
        self._prev_text = text[-200:] if text else ""
        logger.info(f"[STT-stream] '{text}' conf={conf:.2f}")
        return {"text": text, "language": "hinglish", "confidence": conf}

    def set_context(self, agent_reply: str):
        if agent_reply:
            self._prev_text = agent_reply[-200:]

    def transcribe_file(self, path: str) -> dict:
        with open(path, "rb") as f:
            return self.transcribe(f.read())

    def _to_array(self, audio_bytes: bytes) -> np.ndarray:
        buf   = io.BytesIO(audio_bytes)
        arr, sr = sf.read(buf, dtype="float32")
        if arr.ndim == 2:
            arr = arr.mean(axis=1)
        if sr != 16000:
            arr = librosa.resample(arr, orig_sr=sr, target_sr=16000)
        return arr

    def _sanitise(self, text: str) -> str:
        dev = sum(1 for c in text if '\u0900' <= c <= '\u097F')
        if dev > 0:
            cleaned = "".join(c for c in text if not ('\u0900' <= c <= '\u097F')).strip()
            logger.warning(f"[STT] Stripped {dev} Devanagari chars: '{text}' -> '{cleaned}'")
            return cleaned
        return text.strip()

    def _confidence(self, result: dict) -> float:
        segs = result.get("segments", [])
        if not segs:
            return 0.5
        avg = sum(s.get("avg_logprob", -1.0) for s in segs) / len(segs)
        return round(max(0.0, min(1.0, 1.0 + avg / 2.0)), 2)