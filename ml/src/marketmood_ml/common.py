"""Shared helpers for the data pipelines: logging, settings, database connection.

Postgres access uses psycopg 3 (the same driver as the backend).
"""

import logging
import os
import sys
from contextlib import contextmanager
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv

# Features computed by pipelines/features.py, in table order.
FEATURE_COLUMNS = [
    "volatility_20d",
    "sharpe_60d",
    "autocorr_lag1",
    "vix_level",
    "vix_change_30d",
    "drawdown_60d",
    "skewness_30d",
    "bb_width",
]

# Columns that exist in the tables but must never be used to train the model.
# fii_flow has no permitted data source yet and is always 0.
EXCLUDED_FEATURES = ["fii_flow"]

# Error codes (see Security & Observability Architecture, error catalogue).
MM_DATA_002 = "MM-DATA-002"  # data-quality gate failed, nothing written
MM_DATA_003 = "MM-DATA-003"  # market data fetch failed after retries
MM_DB_001 = "MM-DB-001"  # database connection or query failed


class PipelineError(Exception):
    """A pipeline failure with an MM-* error code."""

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


def setup_logging(name, level=None):
    """Log to stdout with timestamps. Level from LOG_LEVEL (default INFO)."""
    level = level or os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger(name)


def load_settings():
    """Load .env and return DATABASE_URL.

    Searches upwards from this package (ml/src/marketmood_ml -> ml -> repository
    root), then upwards from the current folder. Keep .env in the repository root.
    Variables already set in the environment (e.g. GitHub Actions secrets) win.
    """
    path = find_dotenv() or find_dotenv(usecwd=True)
    if path:
        load_dotenv(path)
    url = os.getenv("DATABASE_URL")
    if not url:
        raise PipelineError(
            "MM-CONFIG-001",
            "DATABASE_URL is not set. Add it to your .env file (see README).",
        )
    return url


def describe_database_url(url):
    """Return a safe description of the connection (never includes the password)."""
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    if "pooler.supabase.com" in host:
        kind = "Supabase pooler (" + ("session" if parsed.port == 5432 else "transaction") + " mode)"
    elif host.startswith("db.") and host.endswith(".supabase.co"):
        kind = "Supabase direct connection (IPv6 only; GitHub Actions cannot use it)"
    else:
        kind = "non-Supabase host"
    return f"{kind} host={host} port={parsed.port} user={parsed.username} db={parsed.path.lstrip('/')}"


def is_database_error(exc):
    """True if exc comes from the Postgres driver (bad password, host down, SQL error)."""
    import psycopg

    return isinstance(exc, psycopg.Error)


@contextmanager
def db_connection(url):
    """Open a connection; commit on success, roll back on error, always close.

    prepare_threshold=None disables server-side prepared statements, which the
    Supabase pooler in transaction mode (port 6543) does not support.
    """
    import psycopg

    conn = psycopg.connect(url, connect_timeout=15, prepare_threshold=None)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
