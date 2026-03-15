import os
import sqlite3
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

HERE         = os.path.dirname(__file__)
CALLS_DB_PATH = os.getenv("CALLS_DB_PATH", os.path.join(HERE, "call.db"))

IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> str:
    return datetime.now(tz=IST).isoformat(timespec="seconds")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(CALLS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class SessionManager:
    # ── Session lifecycle ────────────────────────────────────────────────────
    def start_session(
        self,
        phone:            str,
        direction:        str = "inbound",
        provider_call_id: Optional[str] = None,
    ) -> str:
        now        = _now_ist()
        caller_id  = self._upsert_caller(phone, now)
        session_id = str(uuid.uuid4())

        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions
                    (id, caller_id, phone_number, direction, status,
                     provider_call_id, created_at)
                VALUES (?, ?, ?, ?, 'initiated', ?, ?)
                """,
                (session_id, caller_id, phone, direction, provider_call_id, now),
            )
            conn.commit()

        logger.info(f"[SM] Session started | id={session_id} | phone={phone} | dir={direction}")
        return session_id

    def update_status(self, session_id: str, status: str):
        now = _now_ist()
        with _get_conn() as conn:
            if status == "in_progress":
                conn.execute(
                    "UPDATE sessions SET status=?, started_at=? WHERE id=?",
                    (status, now, session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET status=? WHERE id=?",
                    (status, session_id),
                )
            conn.commit()
        logger.info(f"[SM] Session status → {status} | id={session_id}")

    def end_session(self, session_id: str, hangup_cause: Optional[str] = None):
        now = _now_ist()
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT started_at FROM sessions WHERE id=?", (session_id,)
            ).fetchone()

            duration = None
            if row and row["started_at"]:
                try:
                    started = datetime.fromisoformat(row["started_at"])
                    ended   = datetime.fromisoformat(now)
                    duration = int((ended - started).total_seconds())
                except Exception:
                    pass

            conn.execute(
                """
                UPDATE sessions
                SET status='completed', ended_at=?, duration_seconds=?, hangup_cause=?
                WHERE id=?
                """,
                (now, duration, hangup_cause, session_id),
            )
            conn.commit()
        logger.info(f"[SM] Session ended | id={session_id} | duration={duration}s")

    # ── Transcripts ──────────────────────────────────────────────────────────

    def save_turn(
        self,
        session_id: str,
        turn_index:  int,
        speaker:     str,          # "caller" | "agent"
        text:        str,
        confidence:  Optional[float] = None,
        audio_start_ms: Optional[int] = None,
        audio_end_ms:   Optional[int] = None,
    ):
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO transcripts
                    (session_id, turn_index, speaker, raw_text,
                     confidence, audio_start_ms, audio_end_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, turn_index, speaker, text,
                 confidence, audio_start_ms, audio_end_ms),
            )
            conn.commit()

    # ── Session context (in-call key/value) ─────────────────────────────────

    def set_context(self, session_id: str, key: str, value):
        import json
        val_str = json.dumps(value) if not isinstance(value, str) else value
        now     = _now_ist()
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO session_context (session_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, key) DO UPDATE
                    SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (session_id, key, val_str, now),
            )
            conn.commit()

    def get_context(self, session_id: str) -> dict:
        import json
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM session_context WHERE session_id=?",
                (session_id,),
            ).fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except Exception:
                result[r["key"]] = r["value"]
        return result

    # ── Caller memory (cross-call) ───────────────────────────────────────────

    def set_caller_memory(self, caller_id: str, key: str, value, source_session: Optional[str] = None):
        import json
        val_str = json.dumps(value) if not isinstance(value, str) else value
        now     = _now_ist()
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO caller_memory
                    (caller_id, key, value, source_session, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(caller_id, key) DO UPDATE
                    SET value=excluded.value,
                        source_session=excluded.source_session,
                        updated_at=excluded.updated_at
                """,
                (caller_id, key, val_str, source_session, now),
            )
            conn.commit()

    # ── Caller history (loaded at session start for prompt context) ──────────

    def get_caller_history(self, phone: str, n: int = 3) -> list:
        with _get_conn() as conn:
            sessions = conn.execute(
                """
                SELECT s.id, s.started_at, s.duration_seconds
                FROM sessions s
                JOIN callers c ON c.id = s.caller_id
                WHERE c.phone_number = ?
                  AND s.status = 'completed'
                ORDER BY s.created_at DESC
                LIMIT ?
                """,
                (phone, n),
            ).fetchall()

            history = []
            for s in sessions:
                turns = conn.execute(
                    """
                    SELECT speaker, raw_text AS text
                    FROM transcripts
                    WHERE session_id = ?
                    ORDER BY turn_index DESC
                    LIMIT 4
                    """,
                    (s["id"],),
                ).fetchall()

                history.append({
                    "session_id":       s["id"],
                    "started_at":       s["started_at"],
                    "duration_seconds": s["duration_seconds"],
                    "last_turns":       [dict(t) for t in reversed(turns)],
                })

        return history

    # ── Flush memory at call end ─────────────────────────────────────────────

    def flush_memory(self, session_id: str, memory):
        try:
            with _get_conn() as conn:
                row = conn.execute(
                    "SELECT caller_id FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
            if not row:
                return
            caller_id = row["caller_id"]
            if memory.products_discussed:
                self.set_caller_memory(
                    caller_id, "last_products_discussed",
                    memory.products_discussed, source_session=session_id,
                )
            if memory.last_intent:
                self.set_caller_memory(
                    caller_id, "last_intent",
                    memory.last_intent, source_session=session_id,
                )
        except Exception as e:
            logger.warning(f"[SM] flush_memory failed: {e}")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _upsert_caller(self, phone: str, now: str) -> str:
        with _get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM callers WHERE phone_number=?", (phone,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE callers SET last_seen_at=?, total_calls=total_calls+1 WHERE id=?",
                    (now, existing["id"]),
                )
                conn.commit()
                return existing["id"]
            else:
                caller_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO callers
                        (id, phone_number, first_seen_at, last_seen_at, total_calls)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (caller_id, phone, now, now),
                )
                conn.commit()
                return caller_id