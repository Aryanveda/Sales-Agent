# AryanVeda / Nimson — End-to-End Voice Agent Architecture Laymap

---

## 1. WHERE YOU ARE NOW (Current State)

```
Browser UI  ──►  FastAPI (port 8000)  ──►  Skynet Agent
                      │
                      ├── /test/transcribe   (Whisper)
                      ├── /test/full         (Gemini)
                      ├── /test/synthesize   (ElevenLabs)
                      ├── /exotel/incoming   (webhook — exists but untested)
                      └── /call/{sid}        (WebSocket — exists but untested)
```

**What works:** Web UI voice chat, text mode, NLU pipeline  
**What doesn't work yet:** Real phone calls (inbound/outbound), caller identity verification, multi-tier pricing lock

---

## 2. WHAT NEEDS TO BE BUILT (Gap Analysis)

| Gap | Impact | Effort |
|-----|--------|--------|
| Exotel number setup + webhook | Calls don't work at all | Low (config only) |
| Caller identity from DB (not self-declared) | Security risk — anyone can fake tier | Medium |
| Separate system prompts per caller type | Wrong pricing shown | Low (code change) |
| Call classification table in DB | No call analytics | Medium |
| Latency reduction in TTS | Slow response feel | Medium |
| Inbound call routing logic | No IVR / routing | Medium |
| Outbound campaign manager | Bulk calls unmanaged | Medium |

---

## 3. EXOTEL SETUP — STEP BY STEP

### 3a. You've done KYC. Now do this:

**Step 1 — Buy a virtual number**
- Login → https://my.exotel.com
- Go to: Phone Numbers → Buy Number
- Choose: India → Landline (cheaper) or Mobile
- Pick a number → Assign to your account
- Note: this is your `EXOTEL_NUMBER` in .env

**Step 2 — Create an App (Flow)**
- Go to: App Bazaar → Create New App → "Connect Caller to your URL"
- App Type: Passthru (forwards audio to your webhook)
- Passthru URL: `http://34.63.219.123:8000/exotel/incoming`
  - ⚠️ Exotel requires HTTP or HTTPS — port 8000 is fine if firewall is open
  - For production: use a domain + HTTPS (get free SSL via Caddy or nginx + certbot)
- Status Callback URL: `http://34.63.219.123:8000/exotel/status`
- Save the App → note the App SID

**Step 3 — Assign App to Number**
- Go to: Phone Numbers → your number → Edit
- Assign the App you just created
- For INBOUND: this app runs when someone calls your Exotel number
- Save

**Step 4 — Test inbound**
- Call your Exotel number from any phone
- Your server should receive POST to `/exotel/incoming`
- Watch gunicorn logs: `screen -r aryanveda`

**Step 5 — Outbound calls**
- Already coded in server.py at `POST /call/outbound`
- Also via `python main.py --call +91XXXXXXXXXX`
- Exotel dials YOU first, then the customer (bridge call)

### 3b. .env values to fill after above steps:
```env
EXOTEL_SID=your_account_sid          # from dashboard top-right
EXOTEL_API_KEY=your_api_key          # Settings → API Keys
EXOTEL_API_TOKEN=your_api_token      # Settings → API Keys
EXOTEL_NUMBER=+91XXXXXXXXXX          # the number you bought
EXOTEL_SUBDOMAIN=api.exotel.com      # keep as is
SERVER_URL=http://34.63.219.123:8000 # your VM public IP
```

---

## 4. IS EXOTEL THE BEST OPTION?

### Comparison for India:

| Provider | Inbound | Outbound | Streaming | Price | Verdict |
|----------|---------|----------|-----------|-------|---------|
| **Exotel** | ✅ | ✅ | ✅ WebSocket | ₹2-4/min | ✅ Best for India, good support |
| Twilio | ✅ | ✅ | ✅ WebSocket | $0.013/min | ❌ Expensive for India, USD billing |
| Plivo | ✅ | ✅ | ✅ | ₹1.5-3/min | ✅ Good alternative, cheaper |
| Servetel | ✅ | ✅ | ❌ No streaming | ₹1-2/min | ❌ No real-time audio |
| MCUBE | ✅ | ✅ | ❌ | ₹1/min | ❌ No streaming |

**Verdict: Exotel is the right choice for your stack.** It has bidirectional WebSocket streaming which is what your `/call/{call_sid}` endpoint uses. Most Indian alternatives don't support this.

**Alternative worth considering:** Plivo — same WebSocket support, 30% cheaper, similar API. Migration would be minimal.

---

## 5. CALLER IDENTITY — FIX THE SECURITY HOLE

### Current Problem:
Anyone can say "main super stockist hoon" and get super pricing. The NLU detects `customer_type` from what the caller SAYS — not from your DB.

### Fix Architecture:

```
Incoming call → phone number known (Exotel sends "From" field)
                      │
                      ▼
              DB lookup: SELECT tier FROM customers WHERE phone = ?
                      │
            ┌─────────┴──────────┐
         Found                Not Found
            │                     │
     tier = "super"          Ask customer type
     tier = "distributor"    → verify with DB after call
     tier = "retailer"       → default to retail pricing
            │
     Lock customer_type in session (cannot be overridden by caller)
```

### DB changes needed:

```sql
-- Add to your existing DB

CREATE TABLE IF NOT EXISTS customers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    phone        TEXT UNIQUE NOT NULL,
    name         TEXT,
    tier         TEXT CHECK(tier IN ('d2c','retailer','distributor','super')) DEFAULT 'retailer',
    area         TEXT,
    credit_limit REAL DEFAULT 0,
    is_active    INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS call_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT,
    phone            TEXT,
    direction        TEXT CHECK(direction IN ('inbound','outbound')),
    caller_tier      TEXT,
    duration_seconds INTEGER,
    turn_count       INTEGER,
    intent_summary   TEXT,   -- JSON: {"check_price":3, "place_order":1}
    products_asked   TEXT,   -- JSON array
    order_placed     INTEGER DEFAULT 0,
    order_value      REAL,
    call_start       TEXT,
    call_end         TEXT,
    hangup_cause     TEXT,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_call_log_phone  ON call_log(phone);
CREATE INDEX IF NOT EXISTS idx_call_log_date   ON call_log(call_start);
```

### Code change in skynet.py — new_session():

```python
def new_session(self, session_id, db_session_id=None,
                phone="unknown", session_manager=None, **kwargs):
    memory = ConversationMemory(session_id)

    # ── LOCK TIER FROM DB — cannot be faked by caller ──
    verified_tier = None
    if phone and phone != "unknown":
        try:
            row = self.conn.execute(
                "SELECT tier, name FROM customers WHERE phone=? AND is_active=1",
                (phone,)
            ).fetchone()
            if row:
                verified_tier      = row["tier"]
                memory.customer_type = verified_tier
                memory.customer_name = row["name"]
                logger.info(f"[Auth] {phone} verified as {verified_tier}")
            else:
                logger.info(f"[Auth] {phone} not in DB — unknown tier")
        except Exception as e:
            logger.warning(f"[Auth] DB lookup failed: {e}")

    self.intent_classifier.reset()
    self.entity_resolver.reset()
    return {
        "session_id":      session_id,
        "db_session_id":   db_session_id,
        "phone":           phone,
        "turn":            0,
        "memory":          memory,
        "verified_tier":   verified_tier,   # ← NEW: locked from DB
        "session_manager": session_manager,
        "last_language":   "hinglish",
    }
```

### Also in _process_turn() — prevent override:

```python
# After NLU — if tier already verified from DB, ignore what caller claims
if session.get("verified_tier"):
    # DB-verified tier wins — NLU cannot override it
    intent_result["entities"]["customer_type"] = session["verified_tier"]
```

---

## 6. SEPARATE SYSTEM PROMPTS PER CALLER TYPE

### Architecture:

```
Caller identified → tier known
                        │
        ┌───────────────┼───────────────┐
      d2c / unknown   retailer     super / distributor
        │               │               │
   D2C_PROMPT    RETAIL_PROMPT    TRADE_PROMPT
   (general)     (retail pricing  (bulk pricing +
   (benefits)     + ordering)      pre-filled contact
                                   + order history)
```

### Changes to prompt.py:

```python
# Add these alongside existing SYSTEM_PROMPT

SYSTEM_PROMPT_D2C = """
[Same base persona as current]

You are speaking with a DIRECT CONSUMER (end user).
- Focus on: product benefits, ingredients, skin/hair concerns
- Pricing: MRP only — never mention trade prices
- Tone: warm, consultative, like a beauty advisor
- Goal: guide to the right product for their need
- Do NOT ask if they are retailer/distributor/super — they are a consumer
"""

SYSTEM_PROMPT_RETAIL = """
[Same base persona]

You are speaking with a RETAILER.
- They buy to resell in their shop
- Pricing: retail column only
- Focus on: margin, fast-moving SKUs, reorder convenience
- Tone: businesslike but friendly — treat them as a regular partner
- You may discuss minimum order quantities
- Goal: confirm order and get delivery address
"""

SYSTEM_PROMPT_TRADE = """
[Same base persona]

You are speaking with a {tier} — a HIGH-VALUE TRADE PARTNER.
- Known contact: {customer_name} from {customer_area}
- Their history: {last_3_orders}
- Pricing: {tier}_total column only — never show retail or MRP
- Tone: treat them like a valued long-term partner, not a new prospect
- Skip basic intro questions — they know your products well
- Focus on: new SKUs, volume deals, pending orders, upcoming schemes
- Goal: maximize order value and confirm dispatch details
"""
```

### In skynet.py — choose prompt dynamically:

```python
def _get_system_prompt(self, session: dict) -> str:
    tier = session.get("verified_tier") or session["memory"].customer_type

    if tier in ("super", "distributor"):
        name  = getattr(session["memory"], "customer_name", "sir")
        area  = getattr(session["memory"], "customer_area", "")
        history = self._get_order_history(session["phone"], n=3)
        return SYSTEM_PROMPT_TRADE.format(
            tier=tier, customer_name=name,
            customer_area=area, last_3_orders=history
        )
    elif tier == "retailer":
        return SYSTEM_PROMPT_RETAIL
    else:
        return SYSTEM_PROMPT_D2C   # default for unknown / d2c
```

---

## 7. LATENCY REDUCTION PLAN

### Current bottleneck chain:
```
Audio received → Whisper STT → NLU (Gemini) → Entity resolve + DB → LLM response → ElevenLabs TTS → Audio out
     ~0.5s            ~1.5s         ~0.8s              ~0.3s            ~1.5s              ~1.2s
                                                                   TOTAL: ~5.8 seconds
```

### Fixes ranked by impact:

**Fix 1 — Stream ElevenLabs TTS (biggest win, ~1.5s saved)**
```python
# Instead of waiting for full audio, stream chunks
# ElevenLabs supports streaming — switch synthesizer to streaming mode
# Start playing audio while still receiving it
import elevenlabs
client = elevenlabs.ElevenLabs(api_key=...)
audio_stream = client.text_to_speech.convert_as_stream(
    voice_id=VOICE_ID,
    text=response_text,
    model_id="eleven_turbo_v2"   # ← turbo model: 2x faster than standard
)
```

**Fix 2 — Switch ElevenLabs model to turbo**
```python
# In tts/synthesizer.py — change model
model_id = "eleven_turbo_v2"    # was: "eleven_multilingual_v2"
# eleven_turbo_v2 = ~400ms latency vs ~1200ms for multilingual
# Quality is slightly lower but fine for voice calls
```

**Fix 3 — Pre-warm Gemini with shorter max_tokens for NLU**
```python
# In intent.py — NLU doesn't need 150 tokens
max_output_tokens = 80   # was 150 — JSON response is tiny
```

**Fix 4 — Cache DB product catalog in memory**
```python
# In skynet.py — load full catalog at startup, search in memory
# Instead of SQL LIKE query per turn
import difflib
self._product_cache = self._load_full_catalog()  # at __init__

def _db_fetch_cached(self, query_text):
    # fuzzy match against in-memory cache — microseconds vs 50ms DB query
    matches = difflib.get_close_matches(query_text.lower(),
                                        self._product_names, n=5, cutoff=0.4)
    return [self._product_cache[m] for m in matches]
```

**Fix 5 — Overlap TTS with next turn's NLU**
```python
# Start NLU classification WHILE TTS is playing
# Currently: TTS plays → user speaks → NLU runs (sequential)
# Better:    TTS plays → detect speech start → begin NLU warmup
```

**Expected result after fixes 1+2+3:** ~3.5s total (from ~5.8s) — noticeable improvement

---

## 8. FULL INBOUND + OUTBOUND CALL FLOW

### Inbound (customer calls your Exotel number):

```
Customer dials Exotel number
        │
Exotel POST → /exotel/incoming
        │
        ├── Extract: CallSid, From (caller phone)
        ├── DB lookup: customers WHERE phone = From
        ├── Determine tier → choose system prompt
        ├── Start session in DB (call_log)
        │
Exotel returns ExoML:
  <Say> greeting based on tier </Say>
  <Stream url="ws://VM:8000/call/{CallSid}" bidirectional="true" />
        │
WebSocket opens → /call/{CallSid}
        │
Audio loop:
  Caller speaks → bytes arrive → Whisper → Gemini → ElevenLabs → bytes back
        │
Call ends (hangup or end_call intent)
        │
Exotel POST → /exotel/status
        │
Close session, save call_log
```

### Outbound (your agent calls a customer):

```
Trigger: POST /call/outbound {"to": "+91XXXX", "context": "follow_up", "tier": "retailer"}
  OR:    python main.py --call +91XXXX --context "Monthly reorder"
        │
Exotel API called → Exotel dials customer
        │
Customer picks up → Exotel dials YOUR server (bridge)
        │
Exotel POST → /exotel/incoming (with context param)
        │
[Same flow as inbound from here]
```

### Bulk outbound campaign:

```
POST /campaign/start {
  "numbers": ["+91XXX", "+91YYY"],
  "context": "New scheme launched — 20% off on hair oils",
  "delay_seconds": 45,
  "tier_filter": "retailer"   ← only call retailers
}
        │
Background task → dial each number with delay
        │
Results saved to call_log
```

---

## 9. RECOMMENDED FILE STRUCTURE CHANGES

```
Sales-Agent/
├── agent/
│   ├── skynet.py          # add tier-aware session, locked identity
│   ├── prompt.py          # add SYSTEM_PROMPT_D2C, _RETAIL, _TRADE
│   └── router.py          # NEW: chooses prompt + pricing tier
│
├── api/
│   ├── server.py          # add /campaign/start, fix /exotel/incoming
│   └── auth.py            # NEW: phone → tier lookup
│
├── db/
│   ├── schema.sql         # add customers + call_log tables
│   ├── session_manager.py # add call_log writes
│   └── customer_manager.py # NEW: CRUD for customer tier management
│
├── nlu/
│   ├── intent.py          # reduce max_tokens to 80
│   └── entities.py
│
├── tts/
│   └── synthesizer.py     # switch to turbo model + streaming
│
├── voice_chat.html        # already done
├── main.py
└── .env
```

---

## 10. PRIORITY ORDER — WHAT TO BUILD FIRST

```
Week 1 — Make calls actually work
  [1] Exotel: buy number, create app, assign webhook ← do today
  [2] Open GCP port 8000 (or 80 with nginx) ← already discussed
  [3] Test inbound call end-to-end
  [4] Test outbound via POST /call/outbound

Week 2 — Fix identity security
  [5] Add customers table to DB
  [6] Seed it with your known retailers/distributors/supers
  [7] Wire phone lookup in new_session()
  [8] Prevent NLU from overriding verified_tier

Week 3 — Latency + prompts
  [9]  Switch ElevenLabs to turbo model
  [10] Add streaming TTS
  [11] Separate system prompts per tier
  [12] Wire dynamic prompt selection in _generate_response()

Week 4 — Analytics + campaign
  [13] Add call_log table
  [14] Build /campaign/start endpoint
  [15] Basic dashboard to view call history
```

---

## 11. ONE THING TO DO RIGHT NOW

Run this on your VM to test the Exotel webhook is reachable before you even buy the number:

```bash
# From your local machine — simulate what Exotel will POST
curl -X POST http://34.63.219.123:8000/exotel/incoming \
  -d "CallSid=TEST123&From=+919999999999&CallStatus=in-progress"

# Expected response: ExoML XML with <Say> and <Stream>
# If you get connection refused → firewall not open yet
# If you get 500 → server error, check gunicorn logs
```

If that returns XML, your server is ready to receive Exotel calls. Just buy the number and assign the webhook.