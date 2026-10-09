"""Helpers for the backend tests (importable: backend/tests is on the pytest pythonpath)."""

import json
import os
from datetime import date, timedelta

import pytest

from app.core.config import Settings

TEST_URL = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set")

FEATURES = ["volatility_20d", "sharpe_60d", "autocorr_lag1", "vix_level", "vix_change_30d", "drawdown_60d",
            "skewness_30d", "bb_width"]  # fmt: skip


def make_settings(**kw):
    base = {
        "llm_provider": "mock",
        "database_url": None,
        "ip_hash_pepper": "test-pepper",
        "cors_origins": ["http://localhost:5173"],
        "chat_daily_limit": 10,
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


def labels_pattern(n):
    """Bull for 120 days, Sideways 60, Crisis 30, Sideways 40, Bull for the rest; one 1-day flip."""
    out = []
    for i in range(n):
        lab = (
            "Bull"
            if i < 120
            else "Sideways"
            if i < 180
            else "Crisis"
            if i < 210
            else "Sideways"
            if i < 250
            else "Bull"
        )
        out.append(lab)
    return out


def seed(conn, n=300, end=None):
    end = end or date.today()
    days, d = [], end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    labels = labels_pattern(n)
    close = 20000.0
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE regime_output, model_registry, chat_feedback, chat_messages, chat_sessions, "
            "usage_daily, answer_cache, "
            "daily_briefs, glossary, market_data, features"
        )
        cur.execute(
            "INSERT INTO model_registry (version, status, train_start, train_end, data_end, config, metrics, "
            "label_map, artifact_path, checksums, is_active) VALUES ('hmm-test', 'experimental', %s, %s, %s, "
            "'{}', '{}', '{}', 'ml/models/hmm-test', '{}', true)",
            (days[0], days[n // 2], days[-1]),
        )
        for i, (day, lab) in enumerate(zip(days, labels, strict=True)):
            step = {"Bull": 0.004, "Sideways": 0.0, "Crisis": -0.01}[lab]
            close *= 1 + step + (0.003 if i % 2 else -0.003)
            vix = {"Bull": 12.0, "Sideways": 17.0, "Crisis": 32.0}[lab]
            raw = "Crisis" if i == 100 else lab  # a one-day flip the 2-day rule ignores
            probs = {"Bull": 0.01, "Sideways": 0.01, "Crisis": 0.01}
            probs[lab] = 0.98
            signals = [
                {
                    "feature": "vix_level",
                    "value": vix,
                    "contribution": 1.2,
                    "direction": "up" if vix > 15 else "down",
                },
                {"feature": "drawdown_60d", "value": -0.05, "contribution": 0.8, "direction": "down"},
                {"feature": "volatility_20d", "value": 0.009, "contribution": 0.5, "direction": "up"},
            ]
            cur.execute(
                "INSERT INTO market_data (date, open, high, low, close, volume, vix_close) "
                "VALUES (%s, %s, %s, %s, %s, 0, %s)",
                (day, close, close, close, close, vix),
            )
            cur.execute(
                f"INSERT INTO features (date, {', '.join(FEATURES)}, fii_flow) "
                f"VALUES (%s, {', '.join(['%s'] * 8)}, 0)",
                (day, 0.005 + i / 1e5, 0.1, 0.0, vix, 0.01, -0.05, 0.0, 0.04),
            )
            cur.execute(
                "INSERT INTO regime_output (date, label, confidence, p_bull, p_sideways, p_crisis, "
                "confirmed_label, signals, surrogate_agrees, model_version) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'hmm-test')",
                (day, raw, probs[lab], probs["Bull"], probs["Sideways"], probs["Crisis"], lab,
                 json.dumps(signals), i != n - 1),
            )  # fmt: skip
        cur.execute(
            "INSERT INTO glossary (term, aliases, definition) VALUES "
            "('india vix', '{vix}', 'The NSE volatility index: expected movement over the next 30 days.'), "
            "('drawdown', '{drawdown_60d}', 'How far the price is below its recent peak, as a percentage.'), "
            "('sharpe ratio', '{sharpe_60d}', 'Return divided by volatility over a window of trading days.')"
        )
    return days


def sse_events(text):
    """Parse an SSE body into [(event, data), ...] (comments ignored)."""
    out = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln and not ln.startswith(":")]
        if not lines:
            continue
        event = next(ln[7:] for ln in lines if ln.startswith("event: "))
        data = json.loads(next(ln[6:] for ln in lines if ln.startswith("data: ")))
        out.append((event, data))
    return out
