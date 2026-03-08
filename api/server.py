import logging
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from dotenv import load_dotenv

from agent.skynet import Skynet

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app      = FastAPI(title="AryanVeda Voice Agent")
_agent   = None
_sessions = {}   # persistent sessions across /test/full calls


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global _agent
    logger.info("Loading Skynet...")
    _agent = Skynet()
    logger.info("Server ready.")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "agent": _agent is not None}


# ── Exotel Webhook ────────────────────────────────────────────────────────────

@app.post("/exotel/incoming")
async def exotel_incoming(request: Request):
    form     = await request.form()
    call_sid = form.get("CallSid", str(uuid.uuid4()))
    caller   = form.get("From", "unknown")
    logger.info(f"Incoming call | SID={call_sid} | From={caller}")

    base_url = "ws://localhost:8000"
    greeting = "Namaste! Main Tanmay hoon, AryanVeda ka sales assistant. Kaise madad kar sakta hoon?"

    exoml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="female" language="hi-IN">{greeting}</Say>
    <Stream url="{base_url}/call/{call_sid}" bidirectional="true" />
</Response>"""
    return Response(content=exoml, media_type="application/xml")


@app.post("/exotel/status")
async def exotel_status(request: Request):
    form = await request.form()
    logger.info(f"Call ended | SID={form.get('CallSid')} | Status={form.get('CallStatus')}")
    return Response(content="OK")


# ── WebSocket — live call ─────────────────────────────────────────────────────

@app.websocket("/call/{session_id}")
async def call_handler(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info(f"Call connected | session={session_id}")
    session = _new_session(session_id)

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if audio_bytes in (b"END", b"HANGUP"):
                break

            session["turn"] += 1
            result = _agent.run_turn(audio_bytes, session)

            await websocket.send_json({
                "turn":       session["turn"],
                "transcript": result["transcript"],
                "intent":     result["intent"],
                "action":     result["action"],
                "entities":   result["entities"],
                "response":   result["response_text"],
                "latency_ms": result["latency_ms"],
            })
            await websocket.send_bytes(result["audio_bytes"])

            if result.get("end_call"):
                break

    except WebSocketDisconnect:
        logger.info(f"Disconnected | session={session_id}")
    except Exception as e:
        logger.error(f"Error | session={session_id} | {e}", exc_info=True)
    finally:
        logger.info(f"Call ended | session={session_id} | turns={session['turn']}")


# ── Test endpoints ────────────────────────────────────────────────────────────

@app.post("/test/transcribe")
async def test_transcribe(request: Request):
    body = await request.body()
    return _agent.stt.transcribe(body)


@app.post("/test/synthesize")
async def test_synthesize(request: Request):
    data  = await request.json()
    audio = _agent.tts.synthesizer.speak(data["text"])
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/test/nlu")
async def test_nlu(request: Request):
    data     = await request.json()
    nlu      = _agent.nlu.classify(data["text"])
    entities = _agent.ner.resolve(nlu["entities"])
    return {"nlu": nlu, "entities": entities}


@app.post("/test/full")
async def test_full(request: Request):
    """
    Full conversation turn. Session persists across calls.
    POST {"text": "...", "session_id": "optional-defaults-to-test"}
    """
    data       = await request.json()
    text       = data.get("text", "")
    session_id = data.get("session_id", "test")

    # Get or create persistent session
    if session_id not in _sessions:
        _sessions[session_id] = _new_session(session_id)
    session = _sessions[session_id]
    session["turn"] += 1

    # NLU
    nlu_result = _agent.nlu.classify(text)
    intent     = nlu_result["intent"]
    entities   = _agent.ner.resolve(nlu_result["entities"])
    entities   = _agent._fill_from_session(entities, session)

    # Conversation
    response_text = _agent._converse(text, intent, entities, session)
    _agent._update_session(session, intent, entities)

    return {
        "input":      text,
        "intent":     intent,
        "entities":   entities,
        "action":     intent,
        "response":   response_text,
        "turn":       session["turn"],
        "session_id": session_id,
    }


@app.post("/test/reset")
async def test_reset(request: Request):
    """Reset a test session."""
    data       = await request.json()
    session_id = data.get("session_id", "test")
    _sessions.pop(session_id, None)
    return {"reset": True, "session_id": session_id}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_session(session_id: str) -> dict:
    return {
        "session_id":            session_id,
        "turn":                  0,
        "last_sku":              None,
        "last_distributor":      None,
        "last_product_name":     None,
        "last_distributor_name": None,
        "pending_order":         None,
        "history":               [],
    }