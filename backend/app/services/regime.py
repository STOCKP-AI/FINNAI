"""Build the regime API responses from the cached daily series."""

from datetime import timedelta

from app.core.errors import ApiError
from app.services import briefs, market

DISCLAIMER = "Educational information about market conditions, not investment advice."


def today(settings):
    data, fallback = market.series()
    rows = data["rows"]
    last = rows[-1]
    as_of = last["date"]
    n = market.days_in_regime([r["confirmed_label"] for r in rows])
    warnings = []
    stale = fallback or market.is_stale(as_of, holidays=settings.nse_holidays)
    if stale:
        warnings.append("MM-DATA-001")

    stored = None
    if not fallback:
        try:
            stored = market.brief_for(as_of)
        except ApiError:
            stored = None
    if stored:
        brief = {"text": stored["brief"], "what_changed": stored["what_changed"], "source": stored["source"]}
    else:
        text, changed = briefs.template_brief(briefs.brief_facts(rows))
        brief = {"text": text, "what_changed": changed, "source": "template"}

    return {
        "as_of": as_of,
        "is_stale": stale,
        "regime": {
            "label": last["confirmed_label"],
            "raw_label": last["label"],
            "confidence": round(float(last["confidence"]), 4),
            "probabilities": {
                "bull": round(float(last["p_bull"]), 4),
                "sideways": round(float(last["p_sideways"]), 4),
                "crisis": round(float(last["p_crisis"]), 4),
            },
            "days_in_regime": n,
            "since": rows[-n]["date"],
        },
        "signals": market.describe_signals(last["signals"], _percentiles(as_of) if not fallback else None),
        "signals_approximate": not last["surrogate_agrees"],
        "brief": brief,
        "nifty": market.nifty_stats(rows),
        "model": data["model"],
        "disclaimer": DISCLAIMER,
        "warnings": warnings,
    }


def _percentiles(day):
    try:
        return market.feature_percentiles(market.features_table(), day)
    except ApiError:
        return None


def history(range_):
    rows = market.series()[0]["rows"]
    as_of = rows[-1]["date"]
    days = market.RANGES[range_]
    if days is not None:
        start = as_of - timedelta(days=days)
        rows = [r for r in rows if r["date"] > start]
    points = [
        {
            "date": r["date"],
            "label": r["confirmed_label"],
            "confidence": round(float(r["confidence"]), 4),
            "close": round(float(r["close"]), 2),
        }
        for r in market.downsample(rows)
    ]
    return {"range": range_, "as_of": as_of, "points": points}


def episode_list(regime=None, limit=20):
    rows = market.series()[0]["rows"]
    eps = [e for e in market.episodes(rows) if regime is None or e["regime"] == regime]
    eps = sorted(eps, key=lambda e: e["start"], reverse=True)[:limit]
    for e in eps:
        e.pop("_start_index", None)
    return {"regime": regime, "as_of": rows[-1]["date"], "episodes": eps}
