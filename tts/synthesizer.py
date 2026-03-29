import io
import os
import re
import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)

TTS_ENGINE       = os.getenv("TTS_ENGINE", "auto")
ELEVENLABS_KEY   = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "")

VOICE_SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "data", "recordings", "Tanmay.mp4"
)
VOICE_WAV = os.path.join(
    os.path.dirname(__file__), "..", "data", "recordings", "Tanmay.wav"
)


# ── Text cleanup before TTS ───────────────────────────────────────────────────
# ElevenLabs turbo does not expand abbreviations or mixed units naturally.
# This pass normalises the most common patterns that appear in agent responses.

_UNIT_RE = re.compile(r"(\d+)\s*(ml|gm|g|kg|l|mg)\b", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"[₹$€£]")

def _clean_for_tts(text: str) -> str:
    # Remove any rupee symbols that slipped through (agent should say "rupaye")
    text = _SYMBOL_RE.sub("", text)
    # "180ml" → "180 ml", "100gm" → "100 gm" — prevents ElevenLabs reading as one word
    text = _UNIT_RE.sub(r"\1 \2", text)
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


# ── Audio conversion helpers ──────────────────────────────────────────────────

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


def _to_pcm(input_path: str) -> bytes:
    """Convert any audio file to PCM WAV 8kHz mono (Exotel-compatible)."""
    out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out_path = f.name
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", out_path],
            check=True, capture_output=True,
        )
        with open(out_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"[TTS] PCM conversion failed: {e}")
        return b""
    finally:
        # FIX: always clean up temp file even on ffmpeg failure
        if out_path:
            try:
                os.remove(out_path)
            except Exception:
                pass


def _mp3_to_pcm(mp3_bytes: bytes) -> bytes:
    """Pipe MP3 bytes through ffmpeg → PCM WAV 8kHz mono."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "mp3", "-i", "pipe:0",
             "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le",
             "-f", "wav", "pipe:1"],
            input=mp3_bytes, capture_output=True,
        )
        return proc.stdout if proc.returncode == 0 else b""
    except Exception as e:
        logger.error(f"[TTS] mp3→pcm pipe failed: {e}")
        return b""


# ── ElevenLabs ────────────────────────────────────────────────────────────────

def _speak_elevenlabs(text: str) -> bytes:
    """
    Call ElevenLabs and return PCM WAV bytes (8kHz mono) ready for Exotel.
    FIX 1: converts MP3 output to PCM before returning.
    FIX 2: uses eleven_turbo_v2_5 (low-latency) not eleven_multilingual_v2.
    FIX 3: voice settings tuned for consistent Hinglish sales voice.
    """
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings

        client = ElevenLabs(api_key=ELEVENLABS_KEY)
        audio  = client.text_to_speech.convert(
            voice_id       = ELEVENLABS_VOICE,
            text           = text,
            # FIX 2: eleven_turbo_v2_5 = ~280ms latency vs ~600ms for multilingual_v2
            model_id       = "eleven_turbo_v2_5",
            voice_settings = VoiceSettings(
                # FIX 3: tuned for a consistent, professional Hinglish sales voice
                stability        = 0.5,   # was 0.4 — too low makes voice wander turn-to-turn
                similarity_boost = 0.9,   # was 0.75 — higher = stays on-character
                style            = 0.35,  # slight expressiveness, not robotic
                use_speaker_boost = True,
            ),
            output_format  = "mp3_44100_128",
        )
        mp3_bytes = b"".join(audio)
        logger.info(f"[TTS] ElevenLabs MP3 → {len(mp3_bytes)} bytes, converting to PCM...")

        # FIX 1: convert to PCM 8kHz before returning — gTTS does this, ElevenLabs must too
        pcm = _mp3_to_pcm(mp3_bytes)
        if pcm:
            logger.info(f"[TTS] ElevenLabs PCM → {len(pcm)} bytes")
        return pcm

    except Exception as e:
        logger.error(f"[TTS] ElevenLabs failed: {e}")
        return b""


# ── Synthesizer ───────────────────────────────────────────────────────────────

class Synthesizer:
    def __init__(self):
        self.voice_wav  = os.path.abspath(VOICE_WAV)
        self.voice_mp4  = os.path.abspath(VOICE_SAMPLE)
        self.tts_model  = None
        self.engine     = "gtts"
        self._init_engine()

    def _init_engine(self):
        if not os.path.exists(self.voice_wav) and os.path.exists(self.voice_mp4):
            _mp4_to_wav(self.voice_mp4, self.voice_wav)

        requested = TTS_ENGINE.lower()

        # ElevenLabs
        if requested in ("elevenlabs", "auto"):
            if ELEVENLABS_KEY and ELEVENLABS_VOICE:
                try:
                    from elevenlabs.client import ElevenLabs
                    client = ElevenLabs(api_key=ELEVENLABS_KEY)
                    # FIX 4: actually validate the key — list voices makes a real API call
                    client.voices.get_all()
                    self.engine = "elevenlabs"
                    logger.info("[TTS] Engine: ElevenLabs (key validated)")
                    return
                except ImportError:
                    logger.warning("[TTS] elevenlabs package not installed → pip install elevenlabs")
                except Exception as e:
                    logger.warning(f"[TTS] ElevenLabs key validation failed: {e} → trying next engine")
            elif requested == "elevenlabs":
                logger.error("[TTS] ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID missing in .env")

        # Coqui XTTS-v2
        if requested in ("coqui", "auto"):
            try:
                from TTS.api import TTS
                self.tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
                self.engine    = "coqui"
                logger.info("[TTS] Engine: Coqui XTTS-v2")
                return
            except Exception as e:
                if requested == "coqui":
                    logger.error(f"[TTS] Coqui unavailable: {e}")
                else:
                    logger.warning(f"[TTS] Coqui not available → gTTS fallback")

        self.engine = "gtts"
        logger.info("[TTS] Engine: gTTS (fallback — set TTS_ENGINE=elevenlabs for production)")

    def speak(self, text: str) -> bytes:
        """
        Returns PCM WAV bytes at 8kHz mono for all engines.
        All paths produce the same format — Exotel-compatible.
        """
        if not text or not text.strip():
            return b""

        # FIX 5: clean text before any TTS call (expand units, strip stray symbols)
        cleaned = _clean_for_tts(text)

        try:
            if self.engine == "elevenlabs":
                pcm = _speak_elevenlabs(cleaned)
                return pcm if pcm else self._speak_gtts(cleaned)
            if self.engine == "coqui":
                return self._speak_coqui(cleaned)
            return self._speak_gtts(cleaned)
        except Exception as e:
            logger.error(f"[TTS] speak() failed: {e} → gTTS fallback")
            return self._speak_gtts(cleaned)

    def _speak_coqui(self, text: str) -> bytes:
        raw_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                raw_path = f.name
            self.tts_model.tts_to_file(
                text        = text,
                speaker_wav = self.voice_wav if os.path.exists(self.voice_wav) else None,
                language    = "hi",
                file_path   = raw_path,
            )
            audio = _to_pcm(raw_path)
            logger.info(f"[TTS] Coqui → {len(audio)} bytes PCM")
            return audio
        except Exception as e:
            logger.error(f"[TTS] Coqui generation failed: {e}")
            return b""
        finally:
            if raw_path:
                try:
                    os.remove(raw_path)
                except Exception:
                    pass

    def _speak_gtts(self, text: str) -> bytes:
        try:
            from gtts import gTTS
            buf = io.BytesIO()
            gTTS(text=text, lang="hi", tld="co.in", slow=False).write_to_fp(buf)
            audio = _mp3_to_pcm(buf.getvalue())
            logger.info(f"[TTS] gTTS → {len(audio)} bytes PCM")
            return audio
        except Exception as e:
            logger.error(f"[TTS] gTTS failed: {e}")
            return b""


# ── TTSPipeline ───────────────────────────────────────────────────────────────

class TTSPipeline:
    def __init__(self):
        self.synthesizer = Synthesizer()