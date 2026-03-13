import io
import os
import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)

TTS_ENGINE  = os.getenv("TTS_ENGINE", "auto")   # "coqui" | "gtts" | "auto"

VOICE_SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "data", "recordings", "Tanmay.mp4"
)
VOICE_WAV = os.path.join(
    os.path.dirname(__file__), "..", "data", "recordings", "Tanmay.wav"
)


# ── Audio conversion helpers ─────────────────────────────────────────────────

def _mp4_to_wav(mp4_path: str, wav_path: str) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp4_path,
             "-ar", "22050", "-ac", "1", "-f", "wav", wav_path],
            check=True, capture_output=True,
        )
        logger.info(f"[TTS] Voice sample converted: {wav_path}")
        return True
    except Exception as e:
        logger.error(f"[TTS] ffmpeg mp4→wav failed: {e}")
        return False


def _to_exotel_pcm(input_path: str) -> bytes:
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", out_path],
            check=True, capture_output=True,
        )
        with open(out_path, "rb") as f:
            data = f.read()
        os.remove(out_path)
        return data
    except Exception as e:
        logger.error(f"[TTS] PCM conversion failed: {e}")
        return b""


def _mp3_bytes_to_pcm(mp3_bytes: bytes) -> bytes:
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "mp3", "-i", "pipe:0",
             "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le",
             "-f", "wav", "pipe:1"],
            input=mp3_bytes,
            capture_output=True,
        )
        return proc.stdout if proc.returncode == 0 else b""
    except Exception as e:
        logger.error(f"[TTS] mp3→pcm pipe failed: {e}")
        return b""


# ── Synthesizer ──────────────────────────────────────────────────────────────

class Synthesizer:
    def __init__(self):
        self.voice_wav  = os.path.abspath(VOICE_WAV)
        self.voice_mp4  = os.path.abspath(VOICE_SAMPLE)
        self.tts_model  = None
        self.engine     = "gtts"    # default; may upgrade to coqui below
        self._init_engine()

    def _init_engine(self):
        # Ensure voice sample WAV exists for Coqui cloning
        if not os.path.exists(self.voice_wav) and os.path.exists(self.voice_mp4):
            _mp4_to_wav(self.voice_mp4, self.voice_wav)

        requested = TTS_ENGINE.lower()

        if requested in ("coqui", "auto"):
            try:
                from TTS.api import TTS
                self.tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
                self.engine    = "coqui"
                logger.info("[TTS] Engine: Coqui XTTS-v2")
                return
            except Exception as e:
                if requested == "coqui":
                    logger.error(f"[TTS] Coqui requested but unavailable: {e}")
                else:
                    logger.warning(f"[TTS] Coqui not available: {e} → gTTS fallback")

        self.engine = "gtts"
        logger.info("[TTS] Engine: gTTS")

    def speak(self, text: str) -> bytes:
        if not text or not text.strip():
            return b""
        try:
            if self.engine == "coqui":
                return self._speak_coqui(text)
            return self._speak_gtts(text)
        except Exception as e:
            logger.error(f"[TTS] speak failed: {e} → gTTS fallback")
            return self._speak_gtts(text)

    def _speak_coqui(self, text: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            raw_path = f.name
        try:
            self.tts_model.tts_to_file(
                text        = text,
                speaker_wav = self.voice_wav if os.path.exists(self.voice_wav) else None,
                language    = "hi",
                file_path   = raw_path,
            )
            # Resample to 8 kHz PCM for Exotel
            audio = _to_exotel_pcm(raw_path)
            logger.info(f"[TTS] Coqui → {len(audio)} bytes PCM")
            return audio
        except Exception as e:
            logger.error(f"[TTS] Coqui generation failed: {e}")
            return b""
        finally:
            try:
                os.remove(raw_path)
            except Exception:
                pass

    def _speak_gtts(self, text: str) -> bytes:
        try:
            from gtts import gTTS
            buf = io.BytesIO()
            gTTS(text=text, lang="hi", slow=False).write_to_fp(buf)
            mp3_bytes = buf.getvalue()
            # Convert MP3 → 8 kHz PCM WAV for Exotel
            audio = _mp3_bytes_to_pcm(mp3_bytes)
            logger.info(f"[TTS] gTTS → {len(audio)} bytes PCM")
            return audio
        except Exception as e:
            logger.error(f"[TTS] gTTS failed: {e}")
            return b""


# ── TTSPipeline — kept for import compatibility with skynet.py ────────────────
class TTSPipeline:
    def __init__(self):
        self.synthesizer = Synthesizer()