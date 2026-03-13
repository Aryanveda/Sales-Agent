"""
main.py  —  AryanVeda Sales Agent
==================================
The ONLY file you need to run.

Usage:
    python main.py                          # start server, receive inbound calls
    python main.py --call +91XXXXXXXXXX     # start server + dial one number
    python main.py --call +91XXXX --context "Follow up on last order"
    python main.py --bulk numbers.txt       # start server + run bulk campaign
    python main.py --bulk numbers.txt --delay 45
    python main.py --text "amla oil stock"  # text test, no mic, no real call
    python main.py --loop                   # mic conversation test loop
"""

import os
import sys
import time
import uuid
import json
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
SERVER_URL = os.getenv("SERVER_URL", "")    # public ngrok/VPS URL

# Exotel credentials
EXOTEL_SID       = os.getenv("EXOTEL_SID")
EXOTEL_API_KEY   = os.getenv("EXOTEL_API_KEY")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN")
EXOTEL_NUMBER    = os.getenv("EXOTEL_NUMBER")
EXOTEL_SUBDOMAIN = os.getenv("EXOTEL_SUBDOMAIN", "api.exotel.com")


# =============================================================================
# Ngrok — auto-start and get public URL
# =============================================================================

def start_ngrok(port: int) -> str:
    """
    Start ngrok in background, wait for it to be ready,
    return the public https URL.
    Requires ngrok to be installed and authenticated.
    """
    logger.info("[ngrok] Starting tunnel...")
    subprocess.Popen(
        ["ngrok", "http", str(port)],
        stdout = subprocess.DEVNULL,
        stderr = subprocess.DEVNULL,
    )
    # Wait for ngrok API to be ready
    for _ in range(20):
        time.sleep(1)
        try:
            resp = requests.get("http://localhost:4040/api/tunnels", timeout=2)
            tunnels = resp.json().get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    url = t["public_url"]
                    logger.info(f"[ngrok] Public URL: {url}")
                    return url
        except Exception:
            pass
    logger.error("[ngrok] Could not get public URL. Is ngrok installed and authenticated?")
    return ""


# =============================================================================
# Server — run in background thread
# =============================================================================

def start_server(public_url: str):
    """
    Inject the public URL so server.py / outbound calls use it,
    then start uvicorn in a daemon thread.
    """
    if public_url:
        os.environ["SERVER_URL"] = public_url

    def _run():
        uvicorn.run(
            "api.server:app",
            host   = HOST,
            port   = PORT,
            reload = False,          # reload=False required when running in thread
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info(f"[Server] Starting on {HOST}:{PORT}")

    # Wait until server is accepting connections
    for _ in range(30):
        time.sleep(1)
        try:
            requests.get(f"{BASE_URL}/health", timeout=2)
            logger.info("[Server] Ready.")
            return
        except Exception:
            pass
    logger.error("[Server] Did not become ready in time.")
    sys.exit(1)


# =============================================================================
# Outbound dialler  (logic lives here, not in a separate file)
# =============================================================================

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
        logger.error(f"Missing .env keys for Exotel: {', '.join(missing)}")
        sys.exit(1)


def dial(to_number: str, context: str = "", public_url: str = "") -> dict:
    """
    Tell Exotel to dial `to_number`.
    Exotel will call back /exotel/incoming → server.py → Skynet handles it.

    Flow:
        main.py:dial()
            → Exotel API  (HTTP POST)
                → Exotel dials the number
                    → person picks up
                        → Exotel POST /exotel/incoming  (server.py)
                            → SessionManager creates session
                                → WebSocket opens → Skynet greets → conversation
    """
    _validate_exotel()

    webhook = f"{public_url or SERVER_URL}/exotel/incoming"
    if context:
        webhook += f"?context={requests.utils.quote(context)}"

    payload = {
        "From":           EXOTEL_NUMBER,
        "To":             to_number,
        "Url":            webhook,
        "StatusCallback": f"{public_url or SERVER_URL}/exotel/status",
        "CallType":       "trans",
        "TimeLimit":      "300",
        "TimeOut":        "30",
    }

    try:
        resp = requests.post(_exotel_api_url(), data=payload, timeout=15)
        resp.raise_for_status()
        call = resp.json().get("Call", {})
        logger.info(
            f"[Outbound] Dialled {to_number} | "
            f"SID={call.get('Sid')} | Status={call.get('Status')}"
        )
        return {"success": True, "call_sid": call.get("Sid"),
                "status": call.get("Status"), "to": to_number}

    except requests.HTTPError as e:
        logger.error(f"[Outbound] HTTP {e.response.status_code}: {e.response.text}")
        return {"success": False, "error": str(e), "to": to_number}
    except Exception as e:
        logger.error(f"[Outbound] Failed to dial {to_number}: {e}")
        return {"success": False, "error": str(e), "to": to_number}


def bulk_dial(numbers: list, delay_seconds: int = 30,
              context: str = "", public_url: str = "") -> list:
    """Dial a list of numbers sequentially with a delay between each."""
    results = []
    total   = len(numbers)
    logger.info(f"[Bulk] Campaign | {total} numbers | {delay_seconds}s gap")

    for i, number in enumerate(numbers, 1):
        number = number.strip()
        if not number:
            continue
        logger.info(f"[Bulk] {i}/{total} → {number}")
        result = dial(number, context=context, public_url=public_url)
        results.append(result)
        if i < total:
            logger.info(f"[Bulk] Waiting {delay_seconds}s...")
            time.sleep(delay_seconds)

    ok   = sum(1 for r in results if r["success"])
    fail = total - ok
    logger.info(f"[Bulk] Done | OK={ok} | Failed={fail}")
    return results


# =============================================================================
# Local test helpers (speach.py functionality folded in)
# =============================================================================

def _transcribe(wav_bytes: bytes) -> str:
    resp = requests.post(
        f"{BASE_URL}/test/transcribe",
        data    = wav_bytes,
        headers = {"Content-Type": "application/octet-stream"},
        timeout = 90,
    )
    resp.raise_for_status()
    return resp.json().get("text", "").strip()


def _run_turn(text: str, session_id: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/test/full",
        json    = {"text": text, "session_id": session_id},
        timeout = 45,
    )
    resp.raise_for_status()
    return resp.json()


def _synthesize(text: str) -> bytes:
    resp = requests.post(
        f"{BASE_URL}/test/synthesize",
        json    = {"text": text},
        timeout = 30,
    )
    resp.raise_for_status()
    return resp.content


def _play(audio_bytes: bytes):
    suffix = ".wav" if audio_bytes[:4] == b"RIFF" else ".mp3"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="aryan_")
    tmp.write(audio_bytes)
    tmp.close()
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(tmp.name)
        elif system == "Darwin":
            subprocess.run(["afplay", tmp.name], capture_output=True)
        else:
            for player in [["ffplay", "-nodisp", "-autoexit"], ["mpg123"], ["aplay"]]:
                if subprocess.run(["which", player[0]], capture_output=True).returncode == 0:
                    subprocess.run(player + [tmp.name], capture_output=True)
                    break
    except Exception as e:
        print(f"  [!] Playback failed: {e} — file at {tmp.name}")


def _print_turn(result: dict):
    entities = result.get("entities", {})
    print(f"\n  {'─'*54}")
    print(f"  Turn     : {result.get('turn', '-')}")
    print(f"  Intent   : {result.get('intent', '-')}")
    print(f"  Product  : {entities.get('product_name') or '-'} "
          f"{entities.get('weight') or ''}")
    print(f"  Agent    : {result.get('response', '')}")
    if result.get("followup"):
        print(f"  Followup : {result.get('followup')}")
    print(f"  {'─'*54}")


def _record_voice() -> bytes:
    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        print("[!] pip install sounddevice soundfile")
        sys.exit(1)

    print("\n  🎙  Recording... press Enter to stop")
    chunks  = []
    running = [True]

    def cb(indata, frames, time, status):
        if running[0]:
            chunks.append(indata.copy())

    import numpy as np
    stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=cb)
    stream.start()
    input()
    running[0] = False
    stream.stop()
    stream.close()

    if not chunks:
        return b""

    audio_np = np.concatenate(chunks, axis=0)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio_np, 16000)
    with open(tmp.name, "rb") as f:
        data = f.read()
    try:
        os.remove(tmp.name)
    except Exception:
        pass
    return data


def text_test(text: str):
    """Single text turn — quick pipeline test, no mic."""
    session_id = str(uuid.uuid4())
    print(f"\n  Input : {text}")
    result   = _run_turn(text, session_id)
    response = result.get("response", "")
    followup = result.get("followup", "")
    _print_turn(result)
    full = response + ("  " + followup if followup else "")
    if full.strip():
        _play(_synthesize(full))


def voice_loop():
    """Continuous mic → pipeline → speaker test loop."""
    session_id = str(uuid.uuid4())
    print(f"\n  AryanVeda Voice Agent  —  Test Conversation")
    print(f"  Session : {session_id[:8]}...")
    print("  Commands: 'reset' | 'quit'\n")

    while True:
        try:
            cmd = input("  ⏎ Press Enter to speak (or type command): ").strip().lower()
            if cmd in ("quit", "exit"):
                requests.post(f"{BASE_URL}/test/reset",
                              json={"session_id": session_id}, timeout=5)
                break
            if cmd == "reset":
                requests.post(f"{BASE_URL}/test/reset",
                              json={"session_id": session_id}, timeout=5)
                session_id = str(uuid.uuid4())
                print(f"  New session: {session_id[:8]}...")
                continue

            wav = _record_voice()
            if not wav:
                print("  [!] No audio captured.")
                continue

            print("  ⏳ Transcribing...")
            text = _transcribe(wav)
            if not text:
                print("  [!] Could not transcribe.")
                continue
            print(f"  You   : {text}")

            print("  ⏳ Thinking...")
            result   = _run_turn(text, session_id)
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
            print("\n  Bye!\n")
            break
        except requests.exceptions.ConnectionError:
            print(f"  [!] Server not reachable at {BASE_URL}")
        except Exception as e:
            print(f"  [!] {e}")



def chat_mode():
    """
    Type directly in the terminal — no mic, no real call, no Exotel.
    Session memory persists across all turns until you type quit/reset.
    """
    session_id = "chat-" + str(uuid.uuid4())[:8]

    print("")
    print("  AryanVeda Sales Agent  —  Chat Mode")
    print("  =====================================")
    print(f"  Session : {session_id}")
    print("  Commands: 'reset' = new session | 'quit' = exit")
    print("")

    while True:
        try:
            text = input("  You   : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n  Bye!\n")
            break

        if not text:
            continue

        if text.lower() in ("quit", "exit", "bye"):
            print("\n  Bye!\n")
            break

        if text.lower() == "reset":
            session_id = "chat-" + str(uuid.uuid4())[:8]
            print(f"  Session reset → {session_id}\n")
            continue

        try:
            result   = _run_turn(text, session_id)
            response = result.get("response", "")
            followup = result.get("followup", "")
            intent   = result.get("intent", "-")
            turn     = result.get("turn", "-")
            product  = (result.get("entities") or {}).get("product_name") or "-"

            print("")
            print(f"  Agent  : {response}")
            if followup:
                print(f"         + {followup}")
            print(f"  [{turn}] intent={intent}  product={product}")
            print("")

            if intent == "end_call":
                print("  Session ended by agent.\n")
                break

        except requests.exceptions.ConnectionError:
            print(f"  [!] Cannot reach server at {BASE_URL}")
            print("      Make sure python main.py is running in another terminal.\n")
        except Exception as e:
            print(f"  [!] Error: {e}\n")


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="AryanVeda Sales Agent",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  python main.py                             Start server, wait for inbound calls
  python main.py --call +91XXXXXXXXXX        Start server + dial one number
  python main.py --call +91XXXX --context "Follow up"
  python main.py --bulk numbers.txt          Start server + bulk campaign
  python main.py --bulk numbers.txt --delay 45
  python main.py --text "amla oil stock hai" Quick text test
  python main.py --loop                      Mic conversation test loop
  python main.py --chat                      Type in terminal, no mic needed
        """
    )

    parser.add_argument("--call",    metavar="NUMBER", help="Dial one number after server starts")
    parser.add_argument("--bulk",    metavar="FILE",   help="Path to .txt file, one number per line")
    parser.add_argument("--context", default="",       help="Opening context for outbound call")
    parser.add_argument("--delay",   type=int, default=30, help="Seconds between bulk calls (default 30)")
    parser.add_argument("--text",    metavar="TEXT",   help="Quick text test (no mic, no real call)")
    parser.add_argument("--loop",    action="store_true", help="Mic conversation test loop")
    parser.add_argument("--chat",    action="store_true", help="Type in terminal, no mic needed")
    parser.add_argument("--no-ngrok",action="store_true", help="Skip ngrok (use existing SERVER_URL in .env)")
    args = parser.parse_args()

    print("\n  AryanVeda Sales Agent")
    print("  " + "=" * 50)

    # ── Step 1: ngrok (unless --no-ngrok or SERVER_URL already set) ───────────
    public_url = SERVER_URL
    needs_ngrok = args.call or args.bulk   # only needed for real calls

    if needs_ngrok and not args.no_ngrok:
        if not public_url or "localhost" in public_url:
            public_url = start_ngrok(PORT)
            if not public_url:
                print("\n  [!] ngrok failed. Either:\n"
                      "      1. Install ngrok: https://ngrok.com/download\n"
                      "      2. Set SERVER_URL manually in .env and use --no-ngrok")
                sys.exit(1)
        else:
            logger.info(f"[ngrok] Using existing SERVER_URL: {public_url}")

    # ── Step 2: start server ──────────────────────────────────────────────────
    if not (args.text or args.loop):
        # For text/loop modes the server still needs to run
        pass
    start_server(public_url)

    # ── Step 3: execute chosen mode ───────────────────────────────────────────

    if args.call:
        print(f"\n  Dialling {args.call}...")
        result = dial(args.call, context=args.context, public_url=public_url)
        if result["success"]:
            print(f"  ✓ Call initiated | SID: {result['call_sid']}")
            print(f"  Agent will greet {args.call} automatically via Exotel.")
            print(f"  Waiting for call to complete (Ctrl+C to exit)...\n")
            try:
                while True:
                    time.sleep(5)
            except KeyboardInterrupt:
                print("\n  Exiting. Call continues on Exotel.\n")
        else:
            print(f"  ✗ Failed: {result['error']}")
            sys.exit(1)

    elif args.bulk:
        if not os.path.exists(args.bulk):
            print(f"  [!] File not found: {args.bulk}")
            sys.exit(1)
        with open(args.bulk) as f:
            numbers = [l.strip() for l in f if l.strip()]
        if not numbers:
            print("  [!] No numbers in file.")
            sys.exit(1)

        print(f"\n  Campaign: {len(numbers)} numbers | {args.delay}s gap\n")
        results = bulk_dial(numbers, delay_seconds=args.delay,
                            context=args.context, public_url=public_url)
        print("\n  Campaign Summary:")
        for r in results:
            status = f"OK  (SID: {r.get('call_sid')})" if r["success"] \
                     else f"FAIL ({r.get('error', '')})"
            print(f"    {r['to']:20s}  {status}")

    elif args.text:
        text_test(args.text)

    elif args.loop:
        voice_loop()

    elif args.chat:
        chat_mode()

    else:
        # Default: inbound mode — just keep server alive
        public_url_display = public_url or f"http://{HOST}:{PORT}"
        print(f"\n  Server running at  : http://localhost:{PORT}")
        print(f"  Public URL (ngrok) : {public_url_display}")
        print(f"\n  Set this in Exotel dashboard:")
        print(f"    Webhook URL  → {public_url_display}/exotel/incoming")
        print(f"    Status URL   → {public_url_display}/exotel/status")
        print(f"\n  Waiting for inbound calls... (Ctrl+C to stop)\n")
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            print("\n  Server stopped.\n")