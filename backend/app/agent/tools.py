"""The AI analyst's 7 read-only tools (Full Project Document 11.3).

Each tool reads through db.reader() (READ ONLY transaction as agent_reader), validates its
arguments itself (never trusting the model), and returns small, rounded JSON. Free models are
weaker at multi-step tool use, so descriptions are short and schemas strict.
"""

import json
import logging
import time
from datetime import timedelta

from app.core.errors import ApiError
from app.services import market

log = logging.getLogger("agent")

REGIMES = ["Bull", "Sideways", "Crisis"]
HORIZONS = [21, 63, 126, 252]
MAX_LLM_POINTS = 120


def _schema(name, description, properties=None, required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


SCHEMAS = [
    _schema(
        "get_current_regime",
        "Today's market regime for NIFTY 50: label, confidence, days in regime, as_of date, staleness.",
    ),
    _schema(
        "get_regime_history",
        "Regime and NIFTY close over the last N calendar days, with the dates the regime changed.",
        {"days": {"type": "integer", "minimum": 1, "maximum": 3650, "description": "Calendar days back"}},
        ["days"],
    ),
    _schema(
        "get_historical_episodes",
        "Past stretches of one regime, most recent first: start, end, length, NIFTY % change, "
        "worst drawdown.",
        {
            "regime": {"type": "string", "enum": REGIMES},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        ["regime"],
    ),
    _schema(
        "get_forward_returns",
        "What NIFTY did in the trading days after past entries into a regime: median, 25th and 75th "
        "percentile return and sample size. Historical base rates, not a forecast.",
        {
            "regime": {"type": "string", "enum": REGIMES},
            "horizon_days": {"type": "integer", "enum": HORIZONS, "description": "Trading days ahead"},
        },
        ["regime", "horizon_days"],
    ),
    _schema(
        "explain_signals",
        "The top signals behind the regime on a date (default: latest), with plain-English meaning "
        "and the historical percentile of each value.",
        {"date": {"type": "string", "description": "YYYY-MM-DD; omit for the latest day"}},
    ),
    _schema(
        "get_nifty_stats", "NIFTY 50 last close, day change, 52-week high and low, distance from high, YTD."
    ),
    _schema(
        "lookup_glossary",
        "Definition of a market or MarketMood term (VIX, drawdown, SIP, regime, ...).",
        {"term": {"type": "string", "maxLength": 60}},
        ["term"],
    ),
]

LABELS = {
    "get_current_regime": "Checking today's regime",
    "get_regime_history": "Reading the regime history",
    "get_historical_episodes": "Looking up past episodes",
    "get_forward_returns": "Checking what happened after past regimes",
    "explain_signals": "Reading the signals",
    "get_nifty_stats": "Getting NIFTY statistics",
    "lookup_glossary": "Looking up a definition",
}

UNAVAILABLE = {"error": "This data is unavailable right now. Tell the user; do not guess any numbers."}


class ToolArgumentError(ValueError):
    pass


def _rows():
    return market.series()[0]["rows"]


def _pct(x):
    return round(float(x) * 100, 1)


def get_current_regime(settings):
    data, fallback = market.series()
    rows = data["rows"]
    last = rows[-1]
    n = market.days_in_regime([r["confirmed_label"] for r in rows])
    return {
        "as_of": last["date"].isoformat(),
        "is_stale": fallback or market.is_stale(last["date"], holidays=settings.nse_holidays),
        "regime": last["confirmed_label"],
        "todays_raw_label": last["label"],
        "confidence_pct": _pct(last["confidence"]),
        "probabilities_pct": {
            "Bull": _pct(last["p_bull"]),
            "Sideways": _pct(last["p_sideways"]),
            "Crisis": _pct(last["p_crisis"]),
        },
        "days_in_regime": n,
        "regime_since": rows[-n]["date"].isoformat(),
        "model_status": (data["model"] or {}).get("status"),
    }


def get_regime_history(settings, days):
    days = _int(days, "days", 1, 3650)
    rows = _rows()
    start = rows[-1]["date"] - timedelta(days=days)
    window = [r for r in rows if r["date"] > start] or rows[-1:]
    changes = [
        {"date": b["date"].isoformat(), "from": a["confirmed_label"], "to": b["confirmed_label"]}
        for a, b in zip(window, window[1:], strict=False)
        if a["confirmed_label"] != b["confirmed_label"]
    ]
    counts = {lab: sum(1 for r in window if r["confirmed_label"] == lab) for lab in REGIMES}
    return {
        "from": window[0]["date"].isoformat(),
        "to": window[-1]["date"].isoformat(),
        "trading_days_by_regime": counts,
        "regime_changes": changes[-20:],
        "points": [
            {
                "date": r["date"].isoformat(),
                "regime": r["confirmed_label"],
                "close": round(float(r["close"]), 2),
            }
            for r in market.downsample(window, MAX_LLM_POINTS)
        ],
    }


def get_historical_episodes(settings, regime, limit=5):
    regime = _enum(regime, "regime", REGIMES)
    limit = _int(limit, "limit", 1, 10)
    eps = [e for e in market.episodes(_rows()) if e["regime"] == regime]
    eps = sorted(eps, key=lambda e: e["start"], reverse=True)[:limit]
    return {
        "regime": regime,
        "episodes": [
            {
                "start": e["start"].isoformat(),
                "end": e["end"].isoformat(),
                "trading_days": e["days"],
                "nifty_change_pct": e["nifty_change_pct"],
                "max_drawdown_pct": e["max_drawdown_pct"],
                "ongoing": e["ongoing"],
            }
            for e in eps
        ],
    }


def get_forward_returns(settings, regime, horizon_days):
    regime = _enum(regime, "regime", REGIMES)
    horizon = _int(horizon_days, "horizon_days", 1, 252)
    if horizon not in HORIZONS:
        raise ToolArgumentError(f"horizon_days must be one of {HORIZONS}")
    out = market.forward_returns(_rows(), regime, horizon)
    out["note"] = "Historical base rates from past episodes; not a forecast."
    if out["n"] and out.get("small_sample"):
        out["note"] += " Fewer than 5 episodes: treat with caution."
    return out


def explain_signals(settings, date=None):
    rows = _rows()
    row = rows[-1]
    if date:
        try:
            day = market.parse_date(date)
        except ApiError as exc:
            raise ToolArgumentError("date must be YYYY-MM-DD") from exc
        row = next((r for r in reversed(rows) if r["date"] <= day), None)
        if row is None:
            return {"error": f"No regime data on or before {date}."}
    percentiles = market.feature_percentiles(market.features_table(), row["date"])
    return {
        "date": row["date"].isoformat(),
        "regime": row["confirmed_label"],
        "explanation_is_approximate": not row["surrogate_agrees"],
        "signals": [
            {k: s[k] for k in ("name", "value", "direction", "text", "percentile") if k in s}
            for s in market.describe_signals(row["signals"], percentiles)
        ],
    }


def get_nifty_stats(settings):
    stats = market.nifty_stats(_rows())
    stats["as_of"] = stats["as_of"].isoformat()
    return stats


def lookup_glossary(settings, term):
    if not isinstance(term, str) or not term.strip() or len(term) > 60:
        raise ToolArgumentError("term must be a short string")
    hit, terms = market.glossary(term)
    if hit:
        return {"term": hit["term"], "definition": hit["definition"]}
    return {"error": f"'{term}' is not in the glossary.", "available_terms": terms}


FUNCTIONS = {
    "get_current_regime": get_current_regime,
    "get_regime_history": get_regime_history,
    "get_historical_episodes": get_historical_episodes,
    "get_forward_returns": get_forward_returns,
    "explain_signals": explain_signals,
    "get_nifty_stats": get_nifty_stats,
    "lookup_glossary": lookup_glossary,
}


def _int(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int | float) or int(value) != value:
        raise ToolArgumentError(f"{name} must be an integer")
    if not lo <= int(value) <= hi:
        raise ToolArgumentError(f"{name} must be between {lo} and {hi}")
    return int(value)


def _enum(value, name, allowed):
    if value not in allowed:
        raise ToolArgumentError(f"{name} must be one of {allowed}")
    return value


def run_tool(settings, name, arguments):
    """Run one tool call; never raises.

    Returns (result dict, status, elapsed ms); status is "ok", "invalid" (bad name or
    arguments: the model can retry) or "failed" (data unavailable: MM-TOOL-001).
    """
    started = time.perf_counter()
    fn = FUNCTIONS.get(name)
    try:
        if fn is None:
            result, status = {"error": f"Unknown tool {name!r}."}, "invalid"
        else:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ToolArgumentError("arguments must be a JSON object")
            result, status = fn(settings, **args), "ok"
    except (ToolArgumentError, TypeError, json.JSONDecodeError) as exc:
        result, status = {"error": f"Invalid arguments: {exc}"}, "invalid"
    except Exception as exc:  # database down or a bug: the model is told, the user is not misled
        log.warning("MM-TOOL-001 %s failed: %s", name, exc)
        result, status = dict(UNAVAILABLE), "failed"
    return result, status, int((time.perf_counter() - started) * 1000)
