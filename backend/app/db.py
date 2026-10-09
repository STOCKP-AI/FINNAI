"""Database access: one connection pool, and a read-only mode for everything public.

- The pool (psycopg_pool) opens in the background at start-up, so the API starts even when
  the database is down (/livez stays green, /readyz reports the problem).
- reader(): every query behind public endpoints and AI tools runs in a READ ONLY transaction
  as the agent_reader role (SELECT on market tables only, migration 005). Even a bug or a
  prompt-injected tool argument cannot write or read chat data.
- writer(): chat sessions, messages, quotas, cache - a normal transaction.
- Floats are read at full precision (the Supabase server sets extra_float_digits = 0).
"""

import logging
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from app.core.errors import ApiError

log = logging.getLogger("db")

_pool = None


def _configure(conn):
    conn.execute("SET extra_float_digits = 3")
    conn.execute("SET statement_timeout = '5s'")
    conn.execute("SET application_name = 'marketmood-api'")
    conn.commit()


def open_pool(settings):
    """Create and start the pool (non-blocking). Returns None if DATABASE_URL is not set."""
    global _pool
    if settings.database_url is None:
        log.warning("DATABASE_URL is not set: data endpoints will answer 503 MM-DB-001.")
        return None
    _pool = ConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=1,
        max_size=5,
        timeout=5,
        open=False,
        configure=_configure,
        kwargs={"prepare_threshold": None, "connect_timeout": 10},
        name="marketmood",
    )
    _pool.open(wait=False)
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def set_pool(pool):
    """For tests: use a given pool (or None)."""
    global _pool
    _pool = pool


def get_pool():
    if _pool is None:
        raise ApiError("MM-DB-001", "The database is not configured.")
    return _pool


@contextmanager
def _connection():
    try:
        with get_pool().connection() as conn:
            yield conn
    except PoolTimeout as exc:
        raise ApiError("MM-DB-001") from exc
    except psycopg.errors.QueryCanceled as exc:
        raise ApiError("MM-DB-002") from exc
    except psycopg.OperationalError as exc:
        log.warning("Database error: %s", exc)
        raise ApiError("MM-DB-001") from exc


@contextmanager
def reader():
    """Read-only transaction as agent_reader."""
    with _connection() as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL ROLE agent_reader")
        yield conn


@contextmanager
def writer():
    with _connection() as conn, conn.transaction():
        yield conn


def fetch_all(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def fetch_one(conn, sql, params=None):
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None
