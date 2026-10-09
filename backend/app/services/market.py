"""Regime and market data for the API and the AI tools: SQL plus small pure calculations.

All queries run through db.reader() (read-only, agent_reader). The full daily series is small
(about 2,500 rows), so it is loaded once and cached for 5 minutes; everything else is computed
from it in Python. Staleness is computed per request (it depends on the clock, not the data).
"""

import statistics
import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from cachetools import TTLCache

from app import db
from app.core.errors import ApiError

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(16, 0)  # bars are final after 16:00 IST (same rule as mm-ingest)
LABELS = ("Bull", "Sideways", "Crisis")
RANGES = {"60d": 60, "1y": 365, "5y": 5 * 365, "max": None}
MAX_POINTS = 500

FEATURE_TEXT = {
    "volatility_20d": (
        "Volatility (20 days)",
        "Daily price swings are larger than usual",
        "Daily price swings are smaller than usual",
    ),
    "sharpe_60d": (
        "Risk-adjusted momentum (60 days)",
        "Prices have been rising steadily",
        "Recent returns have been weak for the risk taken",
    ),
    "autocorr_lag1": (
        "Trendiness (30 days)",
        "Daily moves have tended to continue",
        "Daily moves have tended to reverse",
    ),
    "vix_level": (
        "India VIX",
        "Expected volatility (fear) is above its usual level",
        "Expected volatility (fear) is below its usual level",
    ),
    "vix_change_30d": (
        "VIX change (30 days)",
        "Fear has been rising over the last month",
        "Fear has been easing over the last month",
    ),
    "drawdown_60d": (
        "Drawdown from the 60-day high",
        "NIFTY is close to its recent high",
        "NIFTY is well below its recent high",
    ),
    "skewness_30d": (
        "Return skew (30 days)",
        "Recent large moves were mostly up",
        "Recent large moves were mostly down",
    ),
    "bb_width": ("Bollinger band width", "The trading range has widened", "The trading range has narrowed"),
}

SERIES_SQL = """
SELECT r.date, r.label, r.confirmed_label, r.confidence, r.p_bull, r.p_sideways, r.p_crisis,
       r.signals, r.surrogate_agrees, r.model_version, m.close, m.vix_close
FROM regime_output r
JOIN market_data m USING (date)
ORDER BY r.date;
"""

MODEL_SQL = "SELECT version, status FROM model_registry WHERE is_active;"
BRIEF_SQL = "SELECT date, brief, what_changed, source FROM daily_briefs WHERE date = %s;"
FEATURES_SQL = """
SELECT date, volatility_20d, sharpe_60d, autocorr_lag1, vix_level, vix_change_30d, drawdown_60d,
       skewness_30d, bb_width
FROM features ORDER BY date;
"""
GLOSSARY_SQL = """
SELECT term, definition, category FROM glossary
WHERE lower(term) = lower(%(q)s)
   OR lower(%(q)s) = ANY (SELECT lower(a) FROM unnest(aliases) a)
   OR lower(term) LIKE lower(%(q)s) || ' %%'
ORDER BY (lower(term) = lower(%(q)s)) DESC, length(term)
LIMIT 1;
"""
GLOSSARY_TERMS_SQL = "SELECT term FROM glossary ORDER BY term;"

_cache = TTLCache(maxsize=16, ttl=300)
_last_good = {}
_lock = threading.Lock()


def clear_cache():
    with _lock:
        _cache.clear()
        _last_good.clear()


def _cached(key, loader):
    """5-minute cache; if the database fails, fall back to the last good value (marked stale)."""
    with _lock:
        if key in _cache:
            return _cache[key], False
    try:
        value = loader()
    except ApiError:
        with _lock:
            if key in _last_good:
                return _last_good[key], True
        raise
    with _lock:
        _cache[key] = value
        _last_good[key] = value
    return value, False


def _load_series():
    with db.reader() as conn:
        rows = db.fetch_all(conn, SERIES_SQL)
        model = db.fetch_one(conn, MODEL_SQL)
    if not rows:
        raise ApiError("MM-DATA-001", "No regime data yet (run mm-infer).", status=503)
    return {"rows": rows, "model": model}


def series():
    """(data, served_from_fallback). data = {"rows": [...], "model": {...}}."""
    return _cached("series", _load_series)


def features_table():
    def load():
        with db.reader() as conn:
            return db.fetch_all(conn, FEATURES_SQL)

    return _cached("features", load)[0]


def brief_for(day):
    with db.reader() as conn:
        return db.fetch_one(conn, BRIEF_SQL, (day,))


def glossary(term):
    with db.reader() as conn:
        hit = db.fetch_one(conn, GLOSSARY_SQL, {"q": term.strip()})
        terms = None if hit else [r["term"] for r in db.fetch_all(conn, GLOSSARY_TERMS_SQL)]
    return hit, terms


# --- pure calculations (unit-tested without a database) -------------------------------------


def last_trading_day(now=None, holidays=()):
    """The most recent weekday (not a listed holiday) whose session has closed (16:00 IST)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    day = now.date() if now.time() >= MARKET_CLOSE else now.date() - timedelta(days=1)
    holidays = set(holidays)
    while day.weekday() >= 5 or day in holidays:
        day -= timedelta(days=1)
    return day


def is_stale(as_of, now=None, holidays=()):
    return as_of < last_trading_day(now, holidays)


def days_in_regime(labels):
    """Number of trailing rows with the same confirmed label as the last row."""
    if not labels:
        return 0
    last, n = labels[-1], 0
    for lab in reversed(labels):
        if lab != last:
            break
        n += 1
    return n


def downsample(rows, max_points=MAX_POINTS):
    """Evenly spaced rows, always keeping the first and the last."""
    if len(rows) <= max_points:
        return list(rows)
    step = (len(rows) - 1) / (max_points - 1)
    idx = sorted({round(k * step) for k in range(max_points)})
    return [rows[i] for i in idx]


def episodes(rows):
    """Runs of the same confirmed label: start, end, days, NIFTY % change, max drawdown %."""
    out, start = [], 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or rows[i]["confirmed_label"] != rows[start]["confirmed_label"]:
            closes = [float(r["close"]) for r in rows[start:i]]
            peak, worst = closes[0], 0.0
            for c in closes:
                peak = max(peak, c)
                worst = min(worst, c / peak - 1)
            out.append(
                {
                    "regime": rows[start]["confirmed_label"],
                    "start": rows[start]["date"],
                    "end": rows[i - 1]["date"],
                    "days": i - start,
                    "nifty_change_pct": round((closes[-1] / closes[0] - 1) * 100, 2),
                    "max_drawdown_pct": round(worst * 100, 2),
                    "ongoing": i == len(rows),
                    "_start_index": start,
                }
            )
            start = i
    return out


def forward_returns(rows, regime, horizon):
    """NIFTY return `horizon` trading days after each entry into `regime` (first run excluded:
    the data simply starts there, it is not an observed entry)."""
    closes = [float(r["close"]) for r in rows]
    values = []
    for ep in episodes(rows):
        i = ep["_start_index"]
        if ep["regime"] == regime and i > 0 and i + horizon < len(closes):
            values.append(closes[i + horizon] / closes[i] - 1)
    if not values:
        return {"regime": regime, "horizon_days": horizon, "n": 0}
    pcts = [v * 100 for v in values]
    p25, p50, p75 = statistics.quantiles(pcts, n=4, method="inclusive") if len(pcts) > 1 else pcts * 3
    return {
        "regime": regime,
        "horizon_days": horizon,
        "n": len(values),
        "median_pct": round(p50, 2),
        "p25_pct": round(p25, 2),
        "p75_pct": round(p75, 2),
        "small_sample": len(values) < 5,
    }


def nifty_stats(rows):
    closes = [float(r["close"]) for r in rows]
    dates = [r["date"] for r in rows]
    last, as_of = closes[-1], dates[-1]
    year_ago = as_of - timedelta(days=365)
    window = [c for c, d in zip(closes, dates, strict=True) if d > year_ago]
    ytd_base = [c for c, d in zip(closes, dates, strict=True) if d.year < as_of.year]
    return {
        "as_of": as_of,
        "close": round(last, 2),
        "change_pct": round((last / closes[-2] - 1) * 100, 2) if len(closes) > 1 else None,
        "high_52w": round(max(window), 2),
        "low_52w": round(min(window), 2),
        "from_high_pct": round((last / max(window) - 1) * 100, 2),
        "ytd_pct": round((last / ytd_base[-1] - 1) * 100, 2) if ytd_base else None,
    }


def describe_signals(signals, percentiles=None):
    out = []
    for s in signals or []:
        name, up, down = FEATURE_TEXT.get(s["feature"], (s["feature"], "Above usual", "Below usual"))
        item = {
            "feature": s["feature"],
            "name": name,
            "value": s["value"],
            "direction": s["direction"],
            "text": up if s["direction"] == "up" else down,
            "contribution": s["contribution"],
        }
        if percentiles and s["feature"] in percentiles:
            item["percentile"] = percentiles[s["feature"]]
        out.append(item)
    return out


def feature_percentiles(table, day):
    """Percentile (0-100) of each feature's value on `day` within its full history."""
    if not table:
        return {}
    row = next((r for r in reversed(table) if r["date"] <= day), None)
    if row is None:
        return {}
    out = {}
    for col in FEATURE_TEXT:
        today = float(row[col])
        below = sum(1 for r in table if float(r[col]) <= today)
        out[col] = round(below / len(table) * 100, 1)
    return out


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ApiError("MM-REQ-001", "date must be YYYY-MM-DD") from exc
