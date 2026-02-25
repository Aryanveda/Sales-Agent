import logging
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from dotenv import load_dotenv

from agent.skynet import Skynet

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app    = FastAPI(title="AryanVeda Voice Agent")
_agent = None


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
    """
    Exotel calls this when a call connects to the virtual number.
    We respond with ExoML to open a WebSocket stream.
    """
    form     = await request.form()
    call_sid = form.get("CallSid", str(uuid.uuid4()))
    caller   = form.get("From", "unknown")
    logger.info(f"Incoming call | SID={call_sid} | From={caller}")

    base_url = "ws://localhost:8000" # replace with your domain
    greeting = "नमस्ते! मैं AryanVeda का सेल्स असिस्टेंट हूँ। आप किस SKU की जानकारी चाहते हैं?"

    exoml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="female" language="hi-IN">{greeting}</Say>
    <Stream url="{base_url}/call/{call_sid}" bidirectional="true" />
</Response>"""

    return Response(content=exoml, media_type="application/xml")


@app.post("/exotel/status")
async def exotel_status(request: Request):
    """Exotel posts final call status here when call ends."""
    form   = await request.form()
    logger.info(f"Call ended | SID={form.get('CallSid')} | Status={form.get('CallStatus')} | Duration={form.get('RecordingDuration')}s")
    return Response(content="OK")


# ── WebSocket — live call ─────────────────────────────────────────────────────

@app.websocket("/call/{session_id}")
async def call_handler(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info(f"Call connected | session={session_id}")

    session = {
        "session_id":       session_id,
        "turn":             0,
        "last_sku":         None,
        "last_distributor": None,
        "pending_order":    None,
    }

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()

            if audio_bytes in (b"END", b"HANGUP"):
                break

            session["turn"] += 1
            logger.info(f"Turn {session['turn']} | session={session_id}")

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
    return Response(content=audio, media_type="audio/wav")


@app.post("/test/nlu")
async def test_nlu(request: Request):
    data     = await request.json()
    text     = data["text"]
    nlu      = _agent.nlu.classify(text)
    entities = _agent.ner.resolve(nlu["entities"])
    return {"nlu": nlu, "entities": entities}


@app.post("/test/full")
async def test_full(request: Request):
    """
    Simulates a full turn without real audio.
    POST { "text": "mumbai wale ke paas AV-001 ka stock hai kya" }
    Returns the full agent response as if it were a real call turn.
    """
    import io
    import soundfile as sf
    import numpy as np

    data   = await request.json()
    text   = data["text"]

    # Convert text to dummy silent audio to pass through STT bypass
    session = {
        "session_id":       "test",
        "turn":             1,
        "last_sku":         None,
        "last_distributor": None,
        "pending_order":    None,
    }

    # Directly run NLU + decision + SKU without STT for testing
    nlu_result = _agent.nlu.classify(text)
    intent     = nlu_result["intent"]
    entities   = _agent.ner.resolve(nlu_result["entities"])
    entities   = _agent._fill_from_session(entities, session)
    sku_data   = {}
    decision   = _agent._decide(intent, entities, session, sku_data, confidence=1.0)
    action     = decision["action"]
    sku_data   = _agent._execute(action, entities, session)
    response_text, _ = _agent.tts.respond(action, sku_data, entities)

    return {
        "input":    text,
        "intent":   intent,
        "entities": entities,
        "action":   action,
        "response": response_text,
    }