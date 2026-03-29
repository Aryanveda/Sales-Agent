"""
server.py — updated
Key changes over original:
  - WebSocket finally block calls _agent.on_call_end(session) for transcript + order pipeline
  - GET /exports/orders — list today's orders as JSON
  - GET /exports/transcript/{session_uuid} — download transcript file
"""

import logging
import uuid
import os
import requests as http_requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response, JSONResponse, FileResponse

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

from agent.skynet import Skynet
from db.session_manager import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app       = FastAPI(title="AryanVeda Voice Agent")
_agent    = None
_sm       = None
_sessions = {}

SERVER_URL       = os.getenv("SERVER_URL", "http://localhost:8000")
EXOTEL_SID       = os.getenv("EXOTEL_SID")
EXOTEL_API_KEY   = os.getenv("EXOTEL_API_KEY")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN")
EXOTEL_NUMBER    = os.getenv("EXOTEL_NUMBER")
EXOTEL_SUBDOMAIN = os.getenv("EXOTEL_SUBDOMAIN", "api.exotel.com")


@app.on_event("startup")
async def startup():
    global _agent, _sm
    logger.info("Loading Skynet...")
    _agent = Skynet()
    _sm    = SessionManager()
    logger.info("Server ready.")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": _agent is not None}


@app.get("/")
async def serve_ui():
    ui_path = os.path.join(os.path.dirname(__file__), "..", "voice.html")
    if not os.path.exists(ui_path):
        ui_path = "voice.html"
    return FileResponse(ui_path, media_type="text/html")


# ---------------------------------------------------------------------------
# Exotel webhooks
# ---------------------------------------------------------------------------

@app.post("/exotel/incoming")
async def exotel_incoming(request: Request):
    form      = await request.form()
    call_sid  = form.get("CallSid", str(uuid.uuid4()))
    caller    = form.get("From", "unknown")
    context   = request.query_params.get("context", "")
    direction = "outbound" if context else "inbound"

    logger.info(f"{direction.title()} call | SID={call_sid} | From={caller} | context='{context}'")

    session_id = _sm.start_session(
        phone            = caller,
        direction        = direction,
        provider_call_id = call_sid,
    )
    _sessions[call_sid] = {
        "db_session_id": session_id,
        "phone":         caller,
        "context":       context,
    }

    base_url = SERVER_URL.replace("http://", "ws://").replace("https://", "wss://")

    if context:
        greeting = f"Namaste! Main Skynet hoon, AryanVeda ka sales assistant. {context} ke baare mein baat karni thi."
    else:
        greeting = "Namaste! Main Skynet hoon, AryanVeda ka sales assistant. Kaise madad kar sakta hoon?"

    exoml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Male" language="hi-IN">{greeting}</Say>
    <Stream url="{base_url}/call/{call_sid}" bidirectional="true" />
</Response>"""
    return Response(content=exoml, media_type="application/xml")


@app.post("/exotel/status")
async def exotel_status(request: Request):
    form     = await request.form()
    call_sid = form.get("CallSid", "")
    status   = form.get("CallStatus", "")
    logger.info(f"Call ended | SID={call_sid} | Status={status}")

    meta = _sessions.pop(call_sid, None)
    if meta:
        _sm.end_session(
            session_id   = meta["db_session_id"],
            hangup_cause = status,
        )
    return Response(content="OK")


# ---------------------------------------------------------------------------
# Outbound call trigger
# ---------------------------------------------------------------------------

@app.post("/call/outbound")
async def call_outbound(request: Request):
    data    = await request.json()
    to      = data.get("to", "").strip()
    context = data.get("context", "")

    if not to:
        return JSONResponse({"error": "to number is required"}, status_code=400)

    missing = [k for k, v in {
        "EXOTEL_SID":       EXOTEL_SID,
        "EXOTEL_API_KEY":   EXOTEL_API_KEY,
        "EXOTEL_API_TOKEN": EXOTEL_API_TOKEN,
        "EXOTEL_NUMBER":    EXOTEL_NUMBER,
    }.items() if not v]
    if missing:
        return JSONResponse({"error": f"Missing .env keys: {', '.join(missing)}"}, status_code=500)

    api_url = (
        f"https://{EXOTEL_API_KEY}:{EXOTEL_API_TOKEN}"
        f"@{EXOTEL_SUBDOMAIN}/v1/Accounts/{EXOTEL_SID}/Calls/connect.json"
    )

    webhook = f"{SERVER_URL}/exotel/incoming"
    if context:
        webhook += f"?context={http_requests.utils.quote(context)}"

    payload = {
        "From":           EXOTEL_NUMBER,
        "To":             to,
        "Url":            webhook,
        "StatusCallback": f"{SERVER_URL}/exotel/status",
        "CallType":       "trans",
        "TimeLimit":      "300",
        "TimeOut":        "30",
    }

    try:
        resp = http_requests.post(api_url, data=payload, timeout=15)
        resp.raise_for_status()
        call_data = resp.json().get("Call", {})
        logger.info(f"[Outbound] Dialled {to} | SID={call_data.get('Sid')}")
        return {
            "success":  True,
            "to":       to,
            "call_sid": call_data.get("Sid"),
            "status":   call_data.get("Status"),
        }
    except Exception as e:
        logger.error(f"[Outbound] Failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# WebSocket — live audio stream
# ---------------------------------------------------------------------------

@app.websocket("/call/{call_sid}")
async def call_handler(websocket: WebSocket, call_sid: str):
    await websocket.accept()
    logger.info(f"WS connected | call_sid={call_sid}")

    meta   = _sessions.get(call_sid, {})
    db_sid = meta.get("db_session_id")
    phone  = meta.get("phone", "unknown")

    agent_session = _agent.new_session(
        session_id      = call_sid,
        db_session_id   = db_sid,
        phone           = phone,
        session_manager = _sm,
    )

    if db_sid:
        _sm.update_status(db_sid, "in_progress")

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if audio_bytes in (b"END", b"HANGUP"):
                break

            result = _agent.run_turn(audio_bytes, agent_session)

            await websocket.send_json({
                "turn":       agent_session["turn"],
                "transcript": result["transcript"],
                "intent":     result["intent"],
                "entities":   result["entities"],
                "response":   result["response_text"],
                "followup":   result.get("followup_text"),
                "latency_ms": result["latency_ms"],
            })
            await websocket.send_bytes(result["audio_bytes"])

            if result.get("end_call"):
                break

    except WebSocketDisconnect:
        logger.info(f"WS disconnected | call_sid={call_sid}")
    except Exception as e:
        logger.error(f"Error | call_sid={call_sid} | {e}", exc_info=True)
    finally:
        logger.info(f"Call ended | call_sid={call_sid} | turns={agent_session['turn']}")
        if db_sid:
            _sm.flush_memory(db_sid, agent_session["memory"])
            # --- NEW: transcript + order + summary pipeline ---
            _agent.on_call_end(agent_session)


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------

@app.get("/exports/orders")
async def list_orders():
    """Return today's confirmed orders as JSON."""
    orders = _sm.get_orders_today()
    return {"count": len(orders), "orders": orders}


@app.get("/exports/transcript/{session_uuid}")
async def get_transcript(session_uuid: str):
    """Download transcript .txt for a session."""
    export_dir = os.getenv("TRANSCRIPT_DIR", "exports/transcripts")
    # find matching file
    try:
        for f in os.listdir(export_dir):
            if session_uuid[:8] in f and f.endswith(".txt"):
                return FileResponse(
                    os.path.join(export_dir, f),
                    media_type="text/plain",
                    filename=f,
                )
    except FileNotFoundError:
        pass
    return JSONResponse({"error": "Transcript not found"}, status_code=404)


@app.get("/exports/orders/download")
async def download_orders():
    """Download today's Excel order sheet."""
    from datetime import datetime, timezone, timedelta
    IST     = timezone(timedelta(hours=5, minutes=30))
    today   = datetime.now(IST).strftime("%Y-%m-%d")
    path    = os.path.join(os.getenv("EXPORTS_DIR", "exports/orders"), f"{today}_orders.xlsx")
    if not os.path.exists(path):
        return JSONResponse({"error": "No orders today yet"}, status_code=404)
    return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename=f"{today}_orders.xlsx")


# ---------------------------------------------------------------------------
# Test / dev routes (unchanged)
# ---------------------------------------------------------------------------

@app.post("/test/transcribe")
async def test_transcribe(request: Request):
    body = await request.body()
    return _agent.transcriber.transcribe(body)


@app.post("/test/synthesize")
async def test_synthesize(request: Request):
    data  = await request.json()
    audio = _agent.tts.synthesizer.speak(data["text"])
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/test/nlu")
async def test_nlu(request: Request):
    data     = await request.json()
    nlu      = _agent.intent_classifier.classify(data["text"])
    entities = _agent.entity_resolver.resolve(nlu["entities"])
    return {"nlu": nlu, "entities": entities}


@app.post("/test/full")
async def test_full(request: Request):
    data       = await request.json()
    text       = data.get("text", "")
    session_id = data.get("session_id", "test")
    phone      = data.get("phone", "test")

    if session_id not in _sessions:
        _agent.intent_classifier.reset()
        _agent.entity_resolver.reset()
        db_sid = _sm.start_session(phone=phone, direction="inbound") if phone != "test" else None
        _sessions[session_id] = _agent.new_session(
            session_id      = session_id,
            db_session_id   = db_sid,
            phone           = phone,
            session_manager = _sm if phone != "test" else None,
        )
    session = _sessions[session_id]
    result  = _agent.run_turn_text(text, session)

    return {
        "input":      text,
        "intent":     result["intent"],
        "entities":   result["entities"],
        "response":   result["response_text"],
        "followup":   result.get("followup_text"),
        "turn":       session["turn"],
        "session_id": session_id,
        "latency_ms": result.get("latency_ms"),
    }


@app.post("/test/reset")
async def test_reset(request: Request):
    data       = await request.json()
    session_id = data.get("session_id", "test")
    session    = _sessions.pop(session_id, None)
    if session:
        try:
            _sm.flush_memory(session.get("db_session_id") or session_id, session.get("memory"))
            _agent.on_call_end(session)
        except Exception as e:
            logger.warning(f"[test/reset] on_call_end failed: {e}")
    return {"reset": True, "session_id": session_id}


@app.post("/test/end")
async def test_end(request: Request):
    """Called by --chat and --loop on quit/exit to trigger on_call_end pipeline."""
    data       = await request.json()
    session_id = data.get("session_id", "test")
    session    = _sessions.pop(session_id, None)
    if session:
        try:
            _sm.flush_memory(session.get("db_session_id") or session_id, session.get("memory"))
            _agent.on_call_end(session)
            logger.info(f"[test/end] on_call_end completed for {session_id[:8]}")
        except Exception as e:
            logger.warning(f"[test/end] on_call_end failed: {e}")
    return {"ended": True, "session_id": session_id}