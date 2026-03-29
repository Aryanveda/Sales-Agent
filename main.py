import os
import sys
import time
import uuid
import logging
import argparse
import threading
import subprocess
import tempfile
import platform

import uvicorn
import requests
from dotenv import load_dotenv

load_dotenv(override=False)

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

HOST       = os.getenv("HOST", "0.0.0.0")
PORT       = int(os.getenv("PORT", "8000"))
BASE_URL   = f"http://localhost:{PORT}"
SERVER_URL = os.getenv("SERVER_URL", "")

EXOTEL_SID       = os.getenv("EXOTEL_SID")
EXOTEL_API_KEY   = os.getenv("EXOTEL_API_KEY")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN")
EXOTEL_NUMBER    = os.getenv("EXOTEL_NUMBER")
EXOTEL_SUBDOMAIN = os.getenv("EXOTEL_SUBDOMAIN", "api.exotel.com")


def start_ngrok(port: int) -> str:
    logger.info("[ngrok] Starting tunnel...")
    subprocess.Popen(
        ["ngrok", "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(1)
        try:
            tunnels = requests.get("http://localhost:4040/api/tunnels", timeout=2).json().get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    url = t["public_url"]
                    logger.info(f"[ngrok] Public URL: {url}")
                    return url
        except Exception:
            pass
    logger.error("[ngrok] Could not get public URL.")
    return ""


def start_server(public_url: str):
    if public_url:
        os.environ["SERVER_URL"] = public_url

    # server.py is inside api/ package — insert project root so Python resolves it
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    def _run():
        if root not in sys.path:
            sys.path.insert(0, root)
        uvicorn.run("api.server:app", host=HOST, port=PORT, reload=False, log_level="warning")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info(f"[Server] Starting on {HOST}:{PORT}...")

    for _ in range(40):
        time.sleep(1)
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=2)
            if r.json().get("agent"):
                logger.info("[Server] Ready.")
                return
        except Exception:
            pass
    logger.error("[Server] Did not become ready in time.")
    sys.exit(1)


def _exotel_api_url() -> str:
    return (
        f"https://{EXOTEL_API_KEY}:{EXOTEL_API_TOKEN}"
        f"@{EXOTEL_SUBDOMAIN}/v1/Accounts/{EXOTEL_SID}/Calls/connect.json"
    )


def _validate_exotel():
    missing = [k for k, v in {
        "EXOTEL_SID":       EXOTEL_SID,
        "EXOTEL_API_KEY":   EXOTEL_API_KEY,
        "EXOTEL_API_TOKEN": EXOTEL_API_TOKEN,
        "EXOTEL_NUMBER":    EXOTEL_NUMBER,
    }.items() if not v]
    if missing:
        logger.error(f"Missing .env keys: {', '.join(missing)}")
        sys.exit(1)


def dial(to_number: str, context: str = "", public_url: str = "") -> dict:
    _validate_exotel()
    base    = public_url or SERVER_URL
    webhook = f"{base}/exotel/incoming"
    if context:
        webhook += f"?context={requests.utils.quote(context)}"
    payload = {
        "From":           EXOTEL_NUMBER,
        "To":             to_number,
        "Url":            webhook,
        "StatusCallback": f"{base}/exotel/status",
        "CallType":       "trans",
        "TimeLimit":      "300",
        "TimeOut":        "30",
    }
    try:
        resp = requests.post(_exotel_api_url(), data=payload, timeout=15)
        resp.raise_for_status()
        call = resp.json().get("Call", {})
        logger.info(f"[Outbound] Dialled {to_number} | SID={call.get('Sid')} | Status={call.get('Status')}")
        return {"success": True, "call_sid": call.get("Sid"), "status": call.get("Status"), "to": to_number}
    except requests.HTTPError as e:
        logger.error(f"[Outbound] HTTP {e.response.status_code}: {e.response.text}")
        return {"success": False, "error": str(e), "to": to_number}
    except Exception as e:
        logger.error(f"[Outbound] Failed to dial {to_number}: {e}")
        return {"success": False, "error": str(e), "to": to_number}


def bulk_dial(numbers: list, delay_seconds: int = 30, context: str = "", public_url: str = "") -> list:
    results = []
    total   = len(numbers)
    logger.info(f"[Bulk] Campaign | {total} numbers | {delay_seconds}s gap")
    for i, number in enumerate(numbers, 1):
        number = number.strip()
        if not number:
            continue
        logger.info(f"[Bulk] {i}/{total} -> {number}")
        results.append(dial(number, context=context, public_url=public_url))
        if i < total:
            time.sleep(delay_seconds)
    ok = sum(1 for r in results if r["success"])
    logger.info(f"[Bulk] Done | OK={ok} | Failed={total - ok}")
    return results


def _transcribe(wav_bytes: bytes) -> str:
    resp = requests.post(
        f"{BASE_URL}/test/transcribe",
        data=wav_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


def _end_session(session_id: str):
    """Call on_call_end pipeline: saves transcript + Excel on chat quit or reset."""
    try:
        requests.post(f"{BASE_URL}/test/end",
                      json={"session_id": session_id}, timeout=30)
        logger.info(f"[Session] on_call_end triggered for {session_id[:8]}")
    except Exception as e:
        logger.warning(f"[Session] on_call_end failed: {e}")


def _run_turn(text: str, session_id: str, phone: str = "test") -> dict:
    # FIX 3: pass phone so /test/full can wire cross-call memory when a phone is given
    resp = requests.post(
        f"{BASE_URL}/test/full",
        json={"text": text, "session_id": session_id, "phone": phone},
        timeout=45,
    )
    resp.raise_for_status()
    return resp.json()


def _synthesize(text: str) -> bytes:
    resp = requests.post(f"{BASE_URL}/test/synthesize", json={"text": text}, timeout=30)
    resp.raise_for_status()
    return resp.content


def _play(audio_bytes: bytes):
    if not audio_bytes:
        return
    suffix = ".wav" if audio_bytes[:4] == b"RIFF" else ".mp3"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(audio_bytes)
    tmp.close()
    system = platform.system()
    try:
        if system == "Windows":
            # os.startfile opens Windows Media Player as a popup.
            # File is intentionally NOT deleted on Windows — the OS cleans temp files itself.
            # Deleting immediately caused error 0x80070002 (file gone before player loads it).
            os.startfile(tmp.name)
        elif system == "Darwin":
            subprocess.run(["afplay", tmp.name], capture_output=True)
            try:
                os.remove(tmp.name)
            except Exception:
                pass
        else:
            for player in [["ffplay", "-nodisp", "-autoexit"], ["mpg123"], ["aplay"]]:
                if subprocess.run(["which", player[0]], capture_output=True).returncode == 0:
                    subprocess.run(player + [tmp.name], capture_output=True)
                    break
            try:
                os.remove(tmp.name)
            except Exception:
                pass
    except Exception as e:
        print(f"  Playback error: {e} — file saved at {tmp.name}")


def _print_turn(result: dict):
    e   = result.get("entities", {})
    ms  = result.get("latency_ms")
    lat = f"  {ms}ms" if ms else ""
    print(f"\n  {'─' * 54}")
    print(f"  Turn    : {result.get('turn', '-')}{lat}")
    print(f"  Intent  : {result.get('intent', '-')}")
    print(f"  Product : {e.get('product_name') or '-'}  {e.get('weight') or ''}")
    print(f"  Agent   : {result.get('response', '')}")
    if result.get("followup"):
        print(f"  +       : {result.get('followup')}")
    print(f"  {'─' * 54}")


def _record_voice() -> bytes:
    try:
        import sounddevice as sd
        import soundfile as sf
        import numpy as np
    except ImportError:
        print("\n  sounddevice not installed. Run:")
        print("    pip install sounddevice soundfile\n")
        sys.exit(1)

    print("\n  Recording... press Enter to stop")
    chunks, running = [], [True]

    def cb(indata, frames, t, status):
        if running[0]:
            chunks.append(indata.copy())

    stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=cb)
    stream.start()
    input()
    running[0] = False
    stream.stop()
    stream.close()

    if not chunks:
        return b""

    arr = np.concatenate(chunks, axis=0)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, arr, 16000)
    data = open(tmp.name, "rb").read()
    try:
        os.remove(tmp.name)
    except Exception:
        pass
    return data


def text_test(text: str, phone: str = "test"):
    """Single-shot text test: one input, one agent response, play audio."""
    session_id = str(uuid.uuid4())
    print(f"\n  Input : {text}")
    result   = _run_turn(text, session_id, phone=phone)
    response = result.get("response", "")
    followup = result.get("followup", "")
    _print_turn(result)
    full = response + ("  " + followup if followup else "")
    if full.strip():
        _play(_synthesize(full))


def voice_loop(phone: str = "test"):
    """
    --loop mode: speak → Whisper STT → agent → ElevenLabs TTS → playback.
    Press Enter to start each recording. Type 'reset' for a new session.
    Phone is used for cross-call memory if set.
    """
    session_id = str(uuid.uuid4())
    print(f"\n  AryanVeda Voice Agent  [--loop]")
    print(f"  Session : {session_id[:8]}...")
    print(f"  Phone   : {phone}")
    print("  Commands: reset | quit\n")
    while True:
        try:
            cmd = input("  Press Enter to speak (or type reset/quit): ").strip().lower()
            if cmd in ("quit", "exit"):
                print("  Saving session...")
                _end_session(session_id)
                print("  Bye.\n")
                break
            if cmd == "reset":
                _end_session(session_id)
                session_id = str(uuid.uuid4())
                print(f"  New session: {session_id[:8]}...\n")
                continue
            wav = _record_voice()
            if not wav:
                print("  No audio captured.")
                continue
            print("  Transcribing...")
            t0   = time.time()
            text = _transcribe(wav)
            if not text:
                print("  Could not transcribe — try again.")
                continue
            print(f"  You   : {text}")
            result   = _run_turn(text, session_id, phone=phone)
            response = result.get("response", "")
            followup = result.get("followup", "")
            _print_turn(result)
            full = response + ("  " + followup if followup else "")
            if full.strip():
                _play(_synthesize(full))
            if result.get("intent") == "end_call":
                print("\n  Call ended by agent.\n")
                break
        except KeyboardInterrupt:
            print("\n  Saving session...")
            _end_session(session_id)
            print("  Bye.\n")
            break
        except requests.exceptions.ConnectionError:
            print(f"  Server not reachable at {BASE_URL}. Is the server running?")
        except Exception as e:
            print(f"  Error: {e}")


def chat_mode(phone: str = "test"):
    """
    --chat mode: type text → agent responds in text + plays audio.
    Use --phone +91XXXXXXXXXX to enable cross-call memory.
    Type 'reset' for a new session within the same run.
    """
    session_id = "chat-" + str(uuid.uuid4())[:8]
    print(f"\n  AryanVeda Sales Agent — Chat Mode  [--chat]")
    print(f"  Session : {session_id}")
    print(f"  Phone   : {phone}  (use --phone to set for memory)")
    print("  Commands: reset | quit\n")
    while True:
        try:
            text = input("  You   : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Bye.\n")
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit", "bye"):
            print("  Saving session...")
            _end_session(session_id)
            print("\n  Bye.\n")
            break
        if text.lower() == "reset":
            _end_session(session_id)
            session_id = "chat-" + str(uuid.uuid4())[:8]
            print(f"  Session reset -> {session_id}\n")
            continue
        try:
            t0       = time.time()
            result   = _run_turn(text, session_id, phone=phone)
            ms       = int((time.time() - t0) * 1000)
            response = result.get("response", "")
            followup = result.get("followup", "")
            intent   = result.get("intent", "-")
            turn     = result.get("turn", "-")
            ents     = result.get("entities") or {}
            product  = ents.get("product_name") or "-"
            weight   = ents.get("weight") or ""
            print(f"\n  Agent  : {response}")
            if followup:
                print(f"         + {followup}")
            print(f"  [{turn}] intent={intent}  product={product} {weight}  ({ms}ms)\n")
            if intent == "end_call":
                print("  Session ended.\n")
                break
        except requests.exceptions.ConnectionError:
            print(f"  Cannot reach server at {BASE_URL}. Is main.py running?\n")
        except Exception as e:
            print(f"  Error: {e}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AryanVeda Sales Agent")
    parser.add_argument("--call",     metavar="NUMBER",  help="Dial one number via Exotel")
    parser.add_argument("--bulk",     metavar="FILE",    help="Dial numbers from a text file")
    parser.add_argument("--context",  default="",        help="Context string for outbound call")
    parser.add_argument("--delay",    type=int, default=30, help="Seconds between bulk calls")
    parser.add_argument("--text",     metavar="TEXT",    help="Single text turn (no audio)")
    parser.add_argument("--loop",     action="store_true", help="Voice loop: speak → STT → agent → TTS")
    parser.add_argument("--chat",     action="store_true", help="Text chat loop (no audio recording)")
    parser.add_argument("--phone",    default="test",    help="Phone number for cross-call memory (e.g. +919999999999)")
    parser.add_argument("--no-ngrok", action="store_true", help="Skip ngrok even for outbound calls")
    args = parser.parse_args()

    print("\n  AryanVeda Sales Agent")
    print("  " + "=" * 50)

    public_url  = SERVER_URL
    needs_ngrok = bool(args.call or args.bulk)

    if needs_ngrok and not args.no_ngrok:
        if not public_url or "localhost" in public_url:
            public_url = start_ngrok(PORT)
            if not public_url:
                print("\n  ngrok failed. Set SERVER_URL in .env and use --no-ngrok")
                sys.exit(1)
        else:
            logger.info(f"[ngrok] Using SERVER_URL from .env: {public_url}")

    start_server(public_url)

    if args.call:
        result = dial(args.call, context=args.context, public_url=public_url)
        if result["success"]:
            print(f"\n  Call initiated | SID: {result['call_sid']}")
            try:
                while True:
                    time.sleep(5)
            except KeyboardInterrupt:
                print("\n  Exiting.\n")
        else:
            print(f"\n  Failed: {result['error']}")
            sys.exit(1)

    elif args.bulk:
        if not os.path.exists(args.bulk):
            print(f"\n  File not found: {args.bulk}")
            sys.exit(1)
        numbers = [l.strip() for l in open(args.bulk) if l.strip()]
        if not numbers:
            print("\n  No numbers in file.")
            sys.exit(1)
        print(f"\n  Campaign: {len(numbers)} numbers | {args.delay}s gap\n")
        results = bulk_dial(numbers, delay_seconds=args.delay, context=args.context, public_url=public_url)
        print("\n  Campaign Summary:")
        for r in results:
            status = f"OK  (SID: {r.get('call_sid')})" if r["success"] else f"FAIL ({r.get('error', '')})"
            print(f"    {r['to']:20s}  {status}")

    elif args.text:
        text_test(args.text, phone=args.phone)

    elif args.loop:
        voice_loop(phone=args.phone)

    elif args.chat:
        chat_mode(phone=args.phone)

    else:
        url = public_url or f"http://{HOST}:{PORT}"
        print(f"\n  Server         : http://localhost:{PORT}")
        print(f"  Public URL     : {url}")
        print(f"\n  Exotel webhook : {url}/exotel/incoming")
        print(f"  Exotel status  : {url}/exotel/status")
        print(f"\n  Waiting for inbound calls... (Ctrl+C to stop)\n")
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            print("\n  Server stopped.\n")