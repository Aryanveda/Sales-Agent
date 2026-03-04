"""
AryanVeda Voice Test Client
Usage:
    python speach.py --loop       # continuous voice conversation loop
"""

import sys
import os
import json
import tempfile
import subprocess
import platform
import requests
import numpy as np

BASE_URL    = "http://localhost:8000"
SAMPLE_RATE = 16000


def play_audio(filepath: str):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(filepath)
        elif system == "Darwin":
            subprocess.run(["afplay", filepath])
        else:
            subprocess.run(["mpg123", filepath])
    except Exception as e:
        print(f"[!] Could not auto-play: {e} — open manually: {filepath}")


def record_voice() -> bytes:
    """Record from mic until user presses Enter. Returns raw WAV bytes."""
    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        print("[!] Run: pip install sounddevice soundfile")
        sys.exit(1)

    print("\n🎙  Recording... press Enter to stop")
    chunks  = []
    running = [True]

    def callback(indata, frames, time, status):
        if running[0]:
            chunks.append(indata.copy())

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback)
    stream.start()
    input()
    running[0] = False
    stream.stop()
    stream.close()

    if not chunks:
        return b""

    audio_np = np.concatenate(chunks, axis=0)

    # Write to temp file — use delete=False and close before reading (Windows fix)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()                          # close handle so soundfile can write

    sf.write(tmp_path, audio_np, SAMPLE_RATE)

    with open(tmp_path, "rb") as f:
        wav_bytes = f.read()

    try:
        os.remove(tmp_path)              # now safe to delete
    except Exception:
        pass

    return wav_bytes


def transcribe_audio(wav_bytes: bytes) -> str:
    """Send WAV bytes to /test/transcribe and get back text."""
    resp = requests.post(
        f"{BASE_URL}/test/transcribe",
        data=wav_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


def run_turn(text: str):
    """Run one full turn: NLU + TTS + play audio."""
    print(f"\n{'='*60}")
    print(f"  Input   : {text}")
    print(f"{'='*60}")

    # ── Step 1: NLU + decision ────────────────────────────────────
    print("\n[1/2] Running pipeline...")
    nlu_resp = requests.post(f"{BASE_URL}/test/full", json={"text": text}, timeout=30)
    nlu_resp.raise_for_status()
    result = nlu_resp.json()

    print(f"  Intent   : {result.get('intent')}")
    print(f"  Action   : {result.get('action')}")
    print(f"  Entities : {json.dumps(result.get('entities'), ensure_ascii=False)}")
    print(f"  Response : {result.get('response')}")

    response_text = result.get("response", "")
    if not response_text:
        print("\n[!] No response text.")
        return

    # ── Step 2: TTS ───────────────────────────────────────────────
    print("\n[2/2] Synthesizing speech...")
    tts_resp = requests.post(f"{BASE_URL}/test/synthesize", json={"text": response_text}, timeout=30)
    tts_resp.raise_for_status()

    suffix = ".mp3" if tts_resp.headers.get("content-type", "").startswith("audio/mp") else ".wav"

    # Windows-safe temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="aryanveda_")
    audio_path = tmp.name
    tmp.write(tts_resp.content)
    tmp.close()                          # close before os.startfile on Windows

    print(f"  Size     : {len(tts_resp.content)} bytes")
    print(f"\n▶  Playing...\n")
    play_audio(audio_path)


def voice_loop():
    """Continuous mic → transcribe → pipeline → speak loop."""
    print("\n🎤  AryanVeda Voice Agent — Conversation Mode")
    print("    Press Enter to start/stop each recording.")
    print("    Type 'quit' or Ctrl+C to exit.\n")

    while True:
        try:
            cmd = input("⏎  Press Enter to speak (or type 'quit'): ").strip().lower()
            if cmd == "quit":
                print("Bye!")
                break

            wav = record_voice()
            if not wav:
                print("[!] No audio captured.")
                continue

            print("⏳  Transcribing...")
            text = transcribe_audio(wav)
            if not text:
                print("[!] Could not transcribe. Try again.")
                continue

            run_turn(text)

        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--loop" in args:
        voice_loop()
    elif args and args[0] != "--loop":
        run_turn(" ".join(args))
    else:
        wav = record_voice()
        if wav:
            print("⏳  Transcribing...")
            text = transcribe_audio(wav)
            if text:
                run_turn(text)
            else:
                print("[!] Could not transcribe.")