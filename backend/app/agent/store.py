"""Chat storage: sessions, messages (server-authoritative history), daily quota, chip cache.

All functions are synchronous (psycopg pool); api/chat.py calls them in a thread.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app import db
from app.core.errors import ApiError

IST = ZoneInfo("Asia/Kolkata")
HISTORY_TURNS = 10  # messages loaded for the model (FPD 11.5)


def ist_today():
    return datetime.now(IST).date()


def _text(value):
    """PostgreSQL text cannot contain NUL characters; a model or a user could send one."""
    return value.replace("\x00", "") if isinstance(value, str) else value


def ensure_session(session_id, client_hash):
    """Reuse the session only if it exists and belongs to this client; otherwise start a new one."""
    with db.writer() as conn, conn.cursor() as cur:
        if session_id is not None:
            cur.execute(
                "UPDATE chat_sessions SET last_active_at = now() "
                "WHERE id = %s AND client_hash = %s RETURNING id",
                (session_id, client_hash),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        cur.execute("INSERT INTO chat_sessions (client_hash) VALUES (%s) RETURNING id", (client_hash,))
        return cur.fetchone()[0]


def history(session_id, turns=HISTORY_TURNS):
    """The last `turns` messages of a session, oldest first, as OpenAI-format messages."""
    with db.writer() as conn:
        rows = db.fetch_all(
            conn,
            "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY id DESC LIMIT %s",
            (session_id, turns),
        )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def save_exchange(session_id, question, final, answer):
    """Store the user's question and the (guarded) answer; return the answer's message id."""
    tools = [{"name": t["name"], "status": t["status"]} for t in final.tools]
    with db.writer() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, 'user', %s)",
            (session_id, _text(question)),
        )
        cur.execute(
            "INSERT INTO chat_messages "
            "(session_id, role, content, tools, warnings, model, tokens_in, tokens_out) "
            "VALUES (%s, 'assistant', %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                session_id,
                _text(answer),
                Jsonb(tools),
                Jsonb(final.warnings),
                final.model,
                final.tokens_in or None,
                final.tokens_out or None,
            ),
        )
        return cur.fetchone()[0]


def save_feedback(session_id, client_hash, message_id, rating):
    """Record +1 / -1 on an assistant answer of the caller's own session (CHAT-09).

    The last click wins. Raises MM-REQ-003 (404) if the answer is not in that session, so a
    visitor can never rate (or probe) someone else's conversation.
    """
    with db.writer() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chat_feedback (message_id, rating) "
            "SELECT m.id, %s FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
            "WHERE m.id = %s AND m.session_id = %s AND s.client_hash = %s AND m.role = 'assistant' "
            "ON CONFLICT (message_id) DO UPDATE SET rating = EXCLUDED.rating, updated_at = now() "
            "RETURNING message_id",
            (rating, message_id, session_id, client_hash),
        )
        if cur.fetchone() is None:
            raise ApiError("MM-REQ-003", "That answer was not found in this conversation.")


def _take(column, client_hash, limit, day):
    """Atomically add one to a usage_daily counter below `limit`; return the new value or None."""
    assert column in ("chats", "cached")
    with db.writer() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO usage_daily (client_hash, day) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (client_hash, day),
        )
        cur.execute(
            f"UPDATE usage_daily SET {column} = {column} + 1 "  # noqa: S608 - column is one of two names
            f"WHERE client_hash = %s AND day = %s AND {column} < %s RETURNING {column}",
            (client_hash, day, limit),
        )
        row = cur.fetchone()
    return None if row is None else row[0]


def take_quota(client_hash, limit, day=None):
    """Atomically count one chat; return chats left today, or raise MM-QUOTA-001 (429)."""
    used = _take("chats", client_hash, limit, day or ist_today())
    if used is None:
        raise ApiError(
            "MM-QUOTA-001", f"You have used today's {limit} chats. The limit resets at midnight IST."
        )
    return limit - used


def take_cached(client_hash, limit, day=None):
    """Count one cached suggestion answer (looser cap, so they cannot be used to fill the database)."""
    if _take("cached", client_hash, limit, day or ist_today()) is None:
        raise ApiError(
            "MM-QUOTA-001",
            f"You have used today's {limit} suggested answers. The limit resets at midnight IST.",
        )


def refund_quota(client_hash, day=None):
    """Give the chat back when the AI failed (SOA 5.6). `day` is the day the chat was counted."""
    day = day or ist_today()
    with db.writer() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE usage_daily SET chats = greatest(chats - 1, 0) WHERE client_hash = %s AND day = %s",
            (client_hash, day),
        )


def cached_answer(chip_id, regime, as_of, day=None):
    day = day or ist_today()
    with db.writer() as conn:
        return db.fetch_one(
            conn,
            "SELECT answer, tools, model FROM answer_cache WHERE day = %s AND chip_id = %s AND regime = %s "
            "AND as_of = %s",
            (day, chip_id, regime, as_of),
        )


def cache_answer(chip_id, regime, as_of, final, answer, day=None):
    day = day or ist_today()
    tools = [t["name"] for t in final.tools]
    with db.writer() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO answer_cache (day, chip_id, regime, as_of, answer, tools, model) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (day, chip_id, regime) DO UPDATE SET as_of = EXCLUDED.as_of, "
            "answer = EXCLUDED.answer, "
            "tools = EXCLUDED.tools, model = EXCLUDED.model, created_at = now()",
            (day, chip_id, regime, as_of, _text(answer), Jsonb(tools), final.model),
        )
