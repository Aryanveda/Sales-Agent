import io
import os
import logging
import subprocess
import tempfile
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings


logger = logging.getLogger(__name__)

TTS_ENGINE       = os.getenv("TTS_ENGINE", "auto")
ELEVENLABS_KEY   = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE_ID", "")   # voice ID from ElevenLabs dashboard

VOICE_SAMPLE = os.path.join(
    os.path.dirname(__file__), "..", "data", "recordings", "Tanmay.mp4"
)
VOICE_WAV = os.path.join(
    os.path.dirname(__file__), "..", "data", "recordings", "Tanmay.wav"
)


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


def _mp3_to_pcm(mp3_bytes: bytes) -> bytes:
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
    try:
        client = ElevenLabs(api_key=ELEVENLABS_KEY)

        audio = client.text_to_speech.convert(
            voice_id              = ELEVENLABS_VOICE,
            text                  = text,
            model_id              = "eleven_multilingual_v2",
            voice_settings        = VoiceSettings(
                stability         = 0.4,   # lower = more expressive
                similarity_boost  = 0.75,
                style             = 0.3,   # adds natural variation
                use_speaker_boost = True,
            ),
            output_format         = "mp3_44100_128",
        )
        # audio is a generator — consume it
        mp3_bytes = b"".join(audio)
        logger.info(f"[TTS] ElevenLabs → {len(mp3_bytes)} bytes")
        return mp3_bytes

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
                    # Quick connectivity test
                    ElevenLabs(api_key=ELEVENLABS_KEY)
                    self.engine = "elevenlabs"
                    logger.info("[TTS] Engine: ElevenLabs")
                    return
                except ImportError:
                    logger.warning("[TTS] elevenlabs package not installed → pip install elevenlabs")
                except Exception as e:
                    logger.warning(f"[TTS] ElevenLabs init failed: {e}")
            elif requested == "elevenlabs":
                logger.error("[TTS] ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID missing in .env")

        # Coqui
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
        logger.info("[TTS] Engine: gTTS (free fallback — consider ElevenLabs for better quality)")

    def speak(self, text: str) -> bytes:
        if not text or not text.strip():
            return b""
        try:
            if self.engine == "elevenlabs":
                mp3 = _speak_elevenlabs(text)
                return mp3 if mp3 else self._speak_gtts(text)
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
            audio = _to_pcm(raw_path)
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
            gTTS(text=text, lang="hi", tld="co.in", slow=False).write_to_fp(buf)
            mp3_bytes = buf.getvalue()
            audio = _mp3_to_pcm(mp3_bytes)
            logger.info(f"[TTS] gTTS → {len(audio)} bytes PCM")
            return audio
        except Exception as e:
            logger.error(f"[TTS] gTTS failed: {e}")
            return b""


# ── TTSPipeline ───────────────────────────────────────────────────────────────
class TTSPipeline:
    def __init__(self):
        self.synthesizer = Synthesizer()