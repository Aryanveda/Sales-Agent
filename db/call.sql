-- ════════════════════════════════════════════════════════════════════════════════
-- CALLS DATABASE SCHEMA — Session Management & Transcript Storage
-- All timestamps stored in IST (UTC+5:30)
-- ════════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- CALLERS — persistent record of every unique caller (phone number)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS callers (
    id                  TEXT PRIMARY KEY,               -- UUID
    phone_number        TEXT UNIQUE NOT NULL,           -- E.164 format: +91XXXXXXXXXX
    name                TEXT,                           -- resolved caller name (if known)
    first_seen_at       TEXT NOT NULL,                  -- ISO-8601 IST (UTC+5:30)
    last_seen_at        TEXT NOT NULL,                  -- ISO-8601 IST (UTC+5:30)
    total_calls         INTEGER DEFAULT 0,
    preferred_language  TEXT DEFAULT 'en',
    notes               TEXT                            -- human / agent notes about caller
);

CREATE INDEX IF NOT EXISTS idx_callers_phone ON callers(phone_number);

-- ─────────────────────────────────────────────────────────────────────────────
-- SESSIONS — one row per call
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,               -- UUID (session_id)
    caller_id           TEXT NOT NULL REFERENCES callers(id) ON DELETE CASCADE,
    phone_number        TEXT NOT NULL,                  -- denormalised for fast lookup
    direction           TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
    status              TEXT NOT NULL DEFAULT 'initiated'
                            CHECK(status IN (
                                'initiated', 'ringing', 'in_progress',
                                'completed', 'failed', 'no_answer', 'busy'
                            )),
    started_at          TEXT,                           -- ISO-8601 IST, set when call connects
    ended_at            TEXT,                           -- ISO-8601 IST
    duration_seconds    INTEGER,                        -- filled on hangup
    hangup_cause        TEXT,                           -- e.g. NORMAL_CLEARING, USER_BUSY
    provider_call_id    TEXT,                           -- Twilio / Exotel / VAPI call SID
    agent_version       TEXT,                           -- git hash or semver of agent
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes')))
);

CREATE INDEX IF NOT EXISTS idx_sessions_caller    ON sessions(caller_id);
CREATE INDEX IF NOT EXISTS idx_sessions_phone     ON sessions(phone_number);
CREATE INDEX IF NOT EXISTS idx_sessions_status    ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_created   ON sessions(created_at);

-- ─────────────────────────────────────────────────────────────────────────────
-- TRANSCRIPTS — turn-by-turn dialogue stored per session
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transcripts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,                   -- 0-based order within session
    speaker         TEXT NOT NULL CHECK(speaker IN ('caller', 'agent')),
    raw_text        TEXT NOT NULL,                      -- STT output / TTS input
    confidence      REAL,                               -- STT confidence score 0.0–1.0 (caller turns)
    audio_start_ms  INTEGER,                            -- offset from call start
    audio_end_ms    INTEGER,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes'))));

CREATE INDEX IF NOT EXISTS idx_transcripts_session ON transcripts(session_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- SESSION_CONTEXT — key-value bag for in-call memory (intent, cart, etc.)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS session_context (
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    key             TEXT NOT NULL,                      -- e.g. "detected_intent", "cart"
    value           TEXT NOT NULL,                      -- JSON string
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes'))),
    PRIMARY KEY (session_id, key)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- CALLER_MEMORY — long-term facts that persist across calls
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS caller_memory (
    caller_id       TEXT NOT NULL REFERENCES callers(id) ON DELETE CASCADE,
    key             TEXT NOT NULL,                      -- e.g. "preferred_products", "last_order"
    value           TEXT NOT NULL,                      -- JSON string
    source_session  TEXT REFERENCES sessions(id),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes'))),
    PRIMARY KEY (caller_id, key)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- CALL_EVENTS — lightweight audit log (ringing, DTMF, errors, etc.)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS call_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,                      -- e.g. "ringing", "dtmf", "stt_error"
    payload         TEXT,                               -- JSON
    occurred_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+05:30', datetime('now', '+5 hours', '30 minutes')))
);

CREATE INDEX IF NOT EXISTS idx_call_events_session ON call_events(session_id);