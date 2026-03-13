import logging
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response

load_dotenv = __import__('dotenv').load_dotenv
load_dotenv(override=False)

from agent.skynet import Skynet
from db.session_manager import SessionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AryanVeda Voice Agent")
_agent   = None
_sm      = None          # SessionManager (call.db)
_sessions = {}


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


# ─────────────────────────────────────────────────────────────────────────────
# Exotel webhooks
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/exotel/incoming")
async def exotel_incoming(request: Request):
    form     = await request.form()
    call_sid = form.get("CallSid", str(uuid.uuid4()))
    caller   = form.get("From", "unknown")
    logger.info(f"Incoming call | SID={call_sid} | From={caller}")

    # Open a session row in call.db immediately
    session_id = _sm.start_session(
        phone         = caller,
        direction     = "inbound",
        provider_call_id = call_sid,
    )
    # Stash mapping so the websocket handler can look it up by call_sid
    _sessions[call_sid] = {"db_session_id": session_id, "phone": caller}

    base_url = "ws://localhost:8000"
    greeting = "Namaste! Main Skynet hoon, AryanVeda ka sales assistant. Kaise madad kar sakta hoon?"

    exoml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="female" language="hi-IN">{greeting}</Say>
    <Stream url="{base_url}/call/{call_sid}" bidirectional="true" />
</Response>"""
    return Response(content=exoml, media_type="application/xml")


@app.post("/exotel/status")
async def exotel_status(request: Request):
    form     = await request.form()
    call_sid = form.get("CallSid", "")
    status   = form.get("CallStatus", "")
    logger.info(f"Call ended | SID={call_sid} | Status={status}")

    # Close the session in call.db
    meta = _sessions.pop(call_sid, None)
    if meta:
        _sm.end_session(
            session_id  = meta["db_session_id"],
            hangup_cause = status,
        )

    return Response(content="OK")


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket — live audio stream (one turn = one receive_bytes call)
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/call/{call_sid}")
async def call_handler(websocket: WebSocket, call_sid: str):
    await websocket.accept()
    logger.info(f"WS connected | call_sid={call_sid}")

    # Recover db_session_id created in /exotel/incoming
    meta       = _sessions.get(call_sid, {})
    db_sid     = meta.get("db_session_id")
    phone      = meta.get("phone", "unknown")

    # In-memory agent session (ConversationMemory etc.)
    agent_session = _agent.new_session(
        session_id   = call_sid,
        db_session_id = db_sid,
        phone        = phone,
        session_manager = _sm,
    )

    # Mark call as in_progress
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
        turns = agent_session["turn"]
        logger.info(f"Call ended | call_sid={call_sid} | turns={turns}")
        # Persist any remaining context; status will be set by /exotel/status
        if db_sid:
            _sm.flush_memory(db_sid, agent_session["memory"])


# ─────────────────────────────────────────────────────────────────────────────
# Test / dev routes  (unchanged behaviour, session_manager passed in)
# ─────────────────────────────────────────────────────────────────────────────

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

    if session_id not in _sessions:
        _sessions[session_id] = _agent.new_session(
            session_id      = session_id,
            db_session_id   = None,   # no call.db row for test sessions
            phone           = "test",
            session_manager = None,
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
    }


@app.post("/test/reset")
async def test_reset(request: Request):
    data       = await request.json()
    session_id = data.get("session_id", "test")
    _sessions.pop(session_id, None)
    return {"reset": True, "session_id": session_id}