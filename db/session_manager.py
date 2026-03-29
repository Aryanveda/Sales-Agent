import os
import sqlite3
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

HERE           = os.path.dirname(__file__)
CALLS_DB_PATH  = os.getenv("CALLS_DB_PATH", os.path.join(HERE, "call.db"))
TRANSCRIPT_DIR = os.getenv("TRANSCRIPT_DIR", "exports/transcripts")

IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> str:
    return datetime.now(tz=IST).isoformat(timespec="seconds")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(CALLS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _apply_patch():
    """Apply call_patch.sql — adds customer_type, caller_summary, orders tables."""
    patch_path = os.path.join(HERE, "call_patch.sql")
    if not os.path.exists(patch_path):
        return
    with open(patch_path, encoding="utf-8") as f:
        statements = [s.strip() for s in f.read().split(";") if s.strip()
                      and not s.strip().startswith("--")]
    conn = _get_conn()
    for stmt in statements:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                logger.debug(f"[SM] patch skip: {e}")
    conn.commit()
    conn.close()


try:
    _apply_patch()
except Exception as e:
    logger.warning(f"[SM] patch apply failed (non-fatal): {e}")


class SessionManager:

    # ── Session lifecycle ────────────────────────────────────────────────────

    def start_session(self, phone: str, direction: str = "inbound",
                      provider_call_id: Optional[str] = None) -> str:
        now        = _now_ist()
        caller_id  = self._upsert_caller(phone, now)
        session_id = str(uuid.uuid4())
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, caller_id, phone_number, direction, status, provider_call_id, created_at) "
                "VALUES (?, ?, ?, ?, 'initiated', ?, ?)",
                (session_id, caller_id, phone, direction, provider_call_id, now),
            )
            conn.commit()
        logger.info(f"[SM] Session started | id={session_id} | phone={phone}")
        return session_id

    def update_status(self, session_id: str, status: str):
        now = _now_ist()
        with _get_conn() as conn:
            if status == "in_progress":
                conn.execute("UPDATE sessions SET status=?, started_at=? WHERE id=?",
                             (status, now, session_id))
            else:
                conn.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))
            conn.commit()

    def end_session(self, session_id: str, hangup_cause: Optional[str] = None):
        now = _now_ist()
        with _get_conn() as conn:
            row      = conn.execute("SELECT started_at FROM sessions WHERE id=?", (session_id,)).fetchone()
            duration = None
            if row and row["started_at"]:
                try:
                    duration = int((datetime.fromisoformat(now) - datetime.fromisoformat(row["started_at"])).total_seconds())
                except Exception:
                    pass
            conn.execute(
                "UPDATE sessions SET status='completed', ended_at=?, duration_seconds=?, hangup_cause=? WHERE id=?",
                (now, duration, hangup_cause, session_id),
            )
            conn.commit()
        logger.info(f"[SM] Session ended | id={session_id} | duration={duration}s")

    # ── Transcripts ──────────────────────────────────────────────────────────

    def save_turn(self, session_id: str, turn_index: int, speaker: str, text: str,
                  confidence: Optional[float] = None, audio_start_ms: Optional[int] = None,
                  audio_end_ms: Optional[int] = None):
        if not text or not text.strip():
            return
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO transcripts (session_id, turn_index, speaker, raw_text, confidence, audio_start_ms, audio_end_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, turn_index, speaker, text.strip(), confidence, audio_start_ms, audio_end_ms),
            )
            conn.commit()

    def get_turns(self, session_id: str) -> List[Dict]:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT turn_index, speaker, raw_text, confidence FROM transcripts "
                "WHERE session_id=? ORDER BY turn_index ASC", (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def export_transcript(self, session_id: str) -> Optional[str]:
        """Write full transcript as .txt. Returns file path or None."""
        turns = self.get_turns(session_id)
        if not turns:
            return None
        with _get_conn() as conn:
            row = conn.execute("SELECT phone_number, started_at FROM sessions WHERE id=?",
                               (session_id,)).fetchone()
        phone      = ((row["phone_number"] if row else "unknown") or "unknown").replace("+", "").replace(" ", "")
        started_at = (row["started_at"] or _now_ist())[:10] if row else _now_ist()[:10]
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
        path = os.path.join(TRANSCRIPT_DIR, f"{started_at}_{phone}_{session_id[:8]}.txt")
        lines = [
            "AryanVeda / Nimson — Sales Call Transcript",
            f"Session  : {session_id}",
            f"Phone    : {row['phone_number'] if row else 'unknown'}",
            f"Date     : {started_at}", "=" * 60, "",
        ]
        for t in turns:
            role = "CALLER" if t["speaker"] == "caller" else "AGENT "
            conf = f" [{t['confidence']:.0%}]" if t.get("confidence") and t["confidence"] < 1.0 else ""
            lines.append(f"[{t['turn_index']:>3}] {role}{conf}: {t['raw_text']}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            logger.info(f"[SM] Transcript → {path}")
            return path
        except Exception as e:
            logger.error(f"[SM] Transcript write failed: {e}")
            return None

    # ── Session context ──────────────────────────────────────────────────────

    def set_context(self, session_id: str, key: str, value):
        val_str = json.dumps(value) if not isinstance(value, str) else value
        now     = _now_ist()
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO session_context (session_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (session_id, key, val_str, now),
            )
            conn.commit()

    def get_context(self, session_id: str) -> dict:
        with _get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM session_context WHERE session_id=?",
                                (session_id,)).fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except Exception:
                result[r["key"]] = r["value"]
        return result

    # ── Caller memory (cross-call) ───────────────────────────────────────────

    def set_caller_memory(self, caller_id: str, key: str, value,
                          source_session: Optional[str] = None):
        val_str = json.dumps(value) if not isinstance(value, str) else value
        now     = _now_ist()
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO caller_memory (caller_id, key, value, source_session, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(caller_id, key) DO UPDATE SET value=excluded.value, "
                "source_session=excluded.source_session, updated_at=excluded.updated_at",
                (caller_id, key, val_str, source_session, now),
            )
            conn.commit()

    def get_caller_memory(self, caller_id: str) -> dict:
        with _get_conn() as conn:
            rows = conn.execute("SELECT key, value FROM caller_memory WHERE caller_id=?",
                                (caller_id,)).fetchall()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except Exception:
                result[r["key"]] = r["value"]
        return result

    # ── Caller summary (LLM-generated CRM note) ──────────────────────────────

    def get_caller_summary(self, phone: str) -> Optional[str]:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT summary, last_products, last_intent FROM caller_summary WHERE phone_number=?",
                (phone,),
            ).fetchone()
        if not row:
            return None
        parts = [f"Previous call summary: {row['summary']}"]
        if row["last_products"]:
            parts.append(f"Last discussed products: {row['last_products']}")
        if row["last_intent"]:
            parts.append(f"Last call intent: {row['last_intent']}")
        return "\n".join(parts)

    def save_caller_summary(self, phone: str, summary: str,
                            last_products: Optional[str] = None,
                            last_intent: Optional[str] = None):
        now = _now_ist()
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO caller_summary (phone_number, summary, last_products, last_intent, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(phone_number) DO UPDATE SET summary=excluded.summary, "
                "last_products=excluded.last_products, last_intent=excluded.last_intent, updated_at=excluded.updated_at",
                (phone, summary, last_products, last_intent, now),
            )
            conn.commit()
        logger.info(f"[SM] Caller summary saved for {phone}")

    # ── Caller history ───────────────────────────────────────────────────────

    def get_caller_history(self, phone: str, n: int = 3) -> list:
        with _get_conn() as conn:
            sessions = conn.execute(
                "SELECT s.id, s.started_at, s.duration_seconds "
                "FROM sessions s JOIN callers c ON c.id = s.caller_id "
                "WHERE c.phone_number = ? AND s.status = 'completed' "
                "ORDER BY s.created_at DESC LIMIT ?",
                (phone, n),
            ).fetchall()
            history = []
            for s in sessions:
                turns = conn.execute(
                    "SELECT speaker, raw_text AS text FROM transcripts "
                    "WHERE session_id = ? ORDER BY turn_index DESC LIMIT 4",
                    (s["id"],),
                ).fetchall()
                history.append({
                    "session_id":       s["id"],
                    "started_at":       s["started_at"],
                    "duration_seconds": s["duration_seconds"],
                    "last_turns":       [dict(t) for t in reversed(turns)],
                })
        return history

    # ── flush_memory — FIXED ─────────────────────────────────────────────────

    def flush_memory(self, session_id: str, memory):
        """
        Persist in-memory state at call end.
        FIXED: reads memory.history and memory.current_product (real attributes)
        instead of the non-existent memory.products_discussed.
        """
        if not memory:
            return
        try:
            with _get_conn() as conn:
                row = conn.execute("SELECT caller_id FROM sessions WHERE id=?",
                                   (session_id,)).fetchone()
            if not row:
                return
            caller_id = row["caller_id"]

            products = list({h.get("product") for h in memory.history if h.get("product")})
            if products:
                self.set_caller_memory(caller_id, "last_products_discussed",
                                       products, source_session=session_id)
            if memory.history:
                last_intent = memory.history[-1].get("intent", "")
                if last_intent:
                    self.set_caller_memory(caller_id, "last_intent",
                                           last_intent, source_session=session_id)
            if memory.customer_type:
                self.set_caller_memory(caller_id, "customer_type",
                                       memory.customer_type, source_session=session_id)
        except Exception as e:
            logger.warning(f"[SM] flush_memory failed: {e}")

    # ── Orders ───────────────────────────────────────────────────────────────

    def save_order(self, session_id: str, order: Dict, excel_path: str = "") -> int:
        now = _now_ist()
        with _get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO orders (session_id, phone_number, caller_name, customer_type, notes, status, excel_path, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                (session_id, order.get("phone", ""), order.get("caller_name", ""),
                 order.get("customer_type", ""), order.get("notes", ""), excel_path, now),
            )
            order_id = cur.lastrowid
            for item in order.get("items", []):
                conn.execute(
                    "INSERT INTO order_items (order_id, product_name, weight, quantity, unit_price, total_price) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (order_id, item.get("product_name", ""), item.get("weight", ""),
                     item.get("quantity", 0), item.get("unit_price", 0.0), item.get("total_price", 0.0)),
                )
            conn.commit()
        logger.info(f"[SM] Order #{order_id} saved for session {session_id[:8]}")
        return order_id

    def get_orders_today(self) -> List[Dict]:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT o.id, o.phone_number, o.caller_name, o.customer_type, o.notes, o.created_at, "
                "oi.product_name, oi.weight, oi.quantity, oi.unit_price, oi.total_price "
                "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
                "WHERE o.created_at LIKE ? ORDER BY o.created_at",
                (f"{today}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Caller type update ───────────────────────────────────────────────────

    def update_caller_type(self, phone: str, customer_type: str):
        with _get_conn() as conn:
            conn.execute("UPDATE callers SET customer_type=? WHERE phone_number=?",
                         (customer_type, phone))
            conn.commit()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _upsert_caller(self, phone: str, now: str) -> str:
        with _get_conn() as conn:
            existing = conn.execute("SELECT id FROM callers WHERE phone_number=?", (phone,)).fetchone()
            if existing:
                conn.execute("UPDATE callers SET last_seen_at=?, total_calls=total_calls+1 WHERE id=?",
                             (now, existing["id"]))
                conn.commit()
                return existing["id"]
            else:
                caller_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO callers (id, phone_number, first_seen_at, last_seen_at, total_calls) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (caller_id, phone, now, now),
                )
                conn.commit()
                return caller_id