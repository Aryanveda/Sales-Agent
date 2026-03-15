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

# ── Prompt anchors Whisper firmly to Roman-script Hinglish ──────────────────
# Rule: keep this ONLY in Roman script — no Devanagari characters here,
# otherwise Whisper uses it as a cue to output Devanagari.
HINGLISH_PROMPT = (
    "Roman script Hinglish sales call for AryanVeda Nimson herbal products India. "
    "Always write in Roman script, never Devanagari. "
    "Examples: "
    "colour plus shampoo 90 ml ka stock hai, "
    "nimson amla hair oil 180 ml kitne ka hai, "
    "kya coconut oil 500 ml available hai, "
    "boroneem talcum powder price batao, "
    "fruit glow cream 100 gram ka daam kya hai, "
    "vasojelly mix 50 ml order karo, "
    "nimson papaya d-tan face wash ka rate kya hai, "
    "green apple shampoo 500 ml bhejna hai, "
    "hair removing cream 60 gram order dena hai, "
    "gold bleach 43 gram available kya, "
    "sunscreen spf 30 200 ml bhejo, "
    "keshsilk plus oil 450 ml chahiye, "
    "divy cool cool oil 180 ml kitne piece chahiye, "
    "glycerin solution 110 ml stock, "
    "gulab jal rose water 50 ml available, "
    "charcoal face wash 60 ml, "
    "honey almond cream 100 gram, "
    "petroleum jelly 42 gram, "
    "haan sir order karo, "
    "theek hai bilkul, "
    "price batao sir, "
    "stock check karo, "
    "order confirm karo."
)

# Whisper decode options shared across both modes
_DECODE_KWARGS = dict(
    language                  = "hi",       # force Hindi recognition path
    task                      = "transcribe",
    initial_prompt            = HINGLISH_PROMPT,
    fp16                      = False,
    verbose                   = False,
    condition_on_previous_text = True,
    no_speech_threshold       = 0.5,        # skip silent chunks
    logprob_threshold         = -1.0,       # accept low-confidence segments rather than dropping
    compression_ratio_threshold = 2.4,
)


class Transcriber:
    def __init__(self, model_size: str = MODEL_SIZE):
        os.makedirs(MODEL_DIR, exist_ok=True)
        logger.info(f"[STT] Loading Whisper '{model_size}'...")
        self.model = whisper.load_model(model_size, download_root=MODEL_DIR)
        self._prev_text = ""        # used by transcribe_stream for context chaining
        logger.info("[STT] Whisper ready.")

    # ── Full-buffer transcription (test route / non-streaming) ───────────────

    def transcribe(self, audio_bytes: bytes) -> dict:
        if not audio_bytes:
            return {"text": "", "language": "hinglish", "confidence": 0.0}

        audio_array = self._to_array(audio_bytes)
        result      = self.model.transcribe(audio_array, **_DECODE_KWARGS)

        text       = self._sanitise(result.get("text", ""))
        language   = result.get("language", "hi")
        confidence = self._confidence(result)

        logger.info(f"[STT] text='{text}' conf={confidence:.2f} lang={language}")
        return {"text": text, "language": language, "confidence": confidence}

    # ── Streaming / chunked transcription (live WebSocket call) ─────────────

    def transcribe_stream(self, audio_bytes: bytes) -> dict:
        """
        Process one audio chunk from the live call stream.
        Uses previous turn's text as initial_prompt for continuity,
        which drastically reduces Devanagari bleed between turns.
        Returns same dict shape as transcribe().
        """
        if not audio_bytes:
            return {"text": "", "language": "hinglish", "confidence": 0.0}

        audio_array = self._to_array(audio_bytes)

        # Build a context-aware prompt: base prompt + last agent/caller turn
        stream_prompt = HINGLISH_PROMPT
        if self._prev_text:
            stream_prompt += f" {self._prev_text}"

        decode_kwargs = {**_DECODE_KWARGS, "initial_prompt": stream_prompt}
        result        = self.model.transcribe(audio_array, **decode_kwargs)

        text       = self._sanitise(result.get("text", ""))
        language   = result.get("language", "hi")
        confidence = self._confidence(result)

        # Store for next chunk's context
        self._prev_text = text[-120:] if text else ""

        logger.info(f"[STT-stream] text='{text}' conf={confidence:.2f}")
        return {"text": text, "language": language, "confidence": confidence}

    def set_context(self, agent_reply: str):
        """
        Call this after each agent TTS turn so the next STT chunk
        has the agent's last words as context — improves continuity.
        """
        if agent_reply:
            self._prev_text = agent_reply[-120:]

    def transcribe_file(self, path: str) -> dict:
        with open(path, "rb") as f:
            return self.transcribe(f.read())

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _to_array(self, audio_bytes: bytes) -> np.ndarray:
        buf         = io.BytesIO(audio_bytes)
        audio_array, sample_rate = sf.read(buf, dtype="float32")

        if audio_array.ndim == 2:
            audio_array = audio_array.mean(axis=1)

        if sample_rate != 16000:
            audio_array = librosa.resample(
                audio_array, orig_sr=sample_rate, target_sr=16000
            )
        return audio_array

    def _sanitise(self, text: str) -> str:
        """
        Strip any Devanagari characters that slip through despite the prompt.
        Logs a warning so you know it happened.
        """
        cleaned = "".join(
            c for c in text if not ('\u0900' <= c <= '\u097F')
        ).strip()

        devanagari_count = len(text) - len(cleaned.replace(" ", "")) + len(cleaned.replace(" ", ""))
        actual_dev = sum(1 for c in text if '\u0900' <= c <= '\u097F')
        if actual_dev > 0:
            logger.warning(
                f"[STT] Stripped {actual_dev} Devanagari chars from: '{text}' → '{cleaned}'"
            )
        return cleaned

    def _confidence(self, result: dict) -> float:
        segments = result.get("segments", [])
        if not segments:
            return 0.5
        avg_logprob = sum(s.get("avg_logprob", -1.0) for s in segments) / len(segments)
        return round(max(0.0, min(1.0, 1.0 + avg_logprob / 2.0)), 2)