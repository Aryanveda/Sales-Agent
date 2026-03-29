import io
import logging
import numpy as np

logger = logging.getLogger(__name__)

_silero_model    = None
_silero_utils    = None
_silero_failed   = False
SPEECH_THRESHOLD = 0.5   # probability above which a chunk is considered speech
MIN_SPEECH_MS    = 300   # ignore chunks shorter than this
SILENCE_PAD_MS   = 400   # trailing silence before we call it done


def _load_silero():
    global _silero_model, _silero_utils, _silero_failed
    if _silero_failed or _silero_model:
        return _silero_model is not None
    try:
        import torch
        _silero_model, _silero_utils = torch.hub.load(
            repo_or_dir = "snakers4/silero-vad",
            model       = "silero_vad",
            force_reload = False,
            onnx        = False,
        )
        logger.info("[VAD] Silero VAD loaded.")
        return True
    except Exception as e:
        logger.warning(f"[VAD] Silero unavailable ({e}). VAD disabled — all chunks pass through.")
        _silero_failed = True
        return False


class VAD:
    def __init__(self):
        self._available = _load_silero()

    def is_speech(self, audio_bytes: bytes, sample_rate: int = 8000) -> bool:
        """
        Returns True if the audio chunk contains speech.
        Always returns True if Silero is not available.
        """
        if not self._available:
            return True
        try:
            import torch
            arr = self._to_tensor(audio_bytes, sample_rate)
            if arr is None:
                return True
            prob = _silero_model(arr, sample_rate).item()
            logger.debug(f"[VAD] speech_prob={prob:.2f}")
            return prob >= SPEECH_THRESHOLD
        except Exception as e:
            logger.warning(f"[VAD] inference failed: {e}")
            return True

    def is_speech_complete(
        self,
        audio_bytes: bytes,
        sample_rate: int = 8000,
        silence_threshold_ms: int = SILENCE_PAD_MS,
    ) -> bool:
        """
        Checks if the audio ends in silence (speech has finished).
        Splits audio into 30ms windows and checks the tail.
        """
        if not self._available:
            return True
        try:
            import torch
            arr = self._to_tensor(audio_bytes, sample_rate)
            if arr is None:
                return True

            window   = int(sample_rate * 0.03)  # 30ms windows
            n_chunks = len(arr) // window
            if n_chunks < 2:
                return True

            tail_chunks = max(1, int(silence_threshold_ms / 30))
            tail        = arr[-(tail_chunks * window):]
            prob        = _silero_model(tail, sample_rate).item()
            is_silent   = prob < SPEECH_THRESHOLD
            logger.debug(f"[VAD] tail_speech_prob={prob:.2f} → complete={is_silent}")
            return is_silent
        except Exception as e:
            logger.warning(f"[VAD] is_speech_complete failed: {e}")
            return True

    def strip_silence(self, audio_bytes: bytes, sample_rate: int = 8000) -> bytes:
        """
        Trim leading/trailing silence from audio.
        Falls back to raw bytes if Silero unavailable.
        """
        if not self._available:
            return audio_bytes
        try:
            import torch
            import soundfile as sf
            arr = self._to_tensor(audio_bytes, sample_rate)
            if arr is None:
                return audio_bytes

            window = int(sample_rate * 0.03)
            probs  = []
            for i in range(len(arr) // window):
                chunk = arr[i * window:(i + 1) * window]
                p     = _silero_model(chunk.unsqueeze(0), sample_rate).item()
                probs.append(p)

            speech_indices = [i for i, p in enumerate(probs) if p >= SPEECH_THRESHOLD]
            if not speech_indices:
                return audio_bytes

            start = max(0, speech_indices[0] - 1) * window
            end   = min(len(arr), (speech_indices[-1] + 2) * window)
            trimmed = arr[start:end].numpy()

            buf = io.BytesIO()
            sf.write(buf, trimmed, sample_rate, format="WAV")
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"[VAD] strip_silence failed: {e}")
            return audio_bytes

    def _to_tensor(self, audio_bytes: bytes, sample_rate: int):
        try:
            import torch
            import soundfile as sf
            buf = io.BytesIO(audio_bytes)
            arr, sr = sf.read(buf, dtype="float32")
            if arr.ndim == 2:
                arr = arr.mean(axis=1)
            if sr != sample_rate:
                try:
                    import librosa
                    arr = librosa.resample(arr, orig_sr=sr, target_sr=sample_rate)
                except Exception:
                    pass
            return torch.from_numpy(arr).float()
        except Exception as e:
            logger.warning(f"[VAD] audio conversion failed: {e}")
            return None