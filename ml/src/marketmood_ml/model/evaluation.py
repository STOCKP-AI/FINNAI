"""How good is a labelling? Reference labels, reference periods, F1, stability, lag, gates.

Reference labels are an objective, rule-based stand-in for "what really happened". They
look at prices AROUND each day (20 trading days either side), so they are for evaluation
only and never feed the model:

    Crisis   if close / 252-day max close - 1 <= -10% and India VIX >= 25
    Bull     else if close[t+20] / close[t-20] - 1 >= +2%
    Sideways otherwise

The simple benchmark is causal (uses today's features only), for comparison:
    Crisis if VIX > 25 and drawdown_60d < -10%; Bull if sharpe_60d > 0; else Sideways.
"""

import numpy as np
import pandas as pd

from marketmood_ml.model.config import GATES, LABELS, REFERENCE_PERIODS

TRADING_DAYS = 252


def reference_labels(close, vix):
    """Ex-post labels; None where the +/-20-day window does not fit (first/last 20 days)."""
    close = pd.Series(np.asarray(close, dtype=float))
    vix = np.asarray(vix, dtype=float)
    drawdown_252 = close / close.rolling(TRADING_DAYS, min_periods=1).max() - 1
    centred = close.shift(-20) / close.shift(20) - 1
    out = np.where(
        (drawdown_252 <= -0.10) & (vix >= 25),
        "Crisis",
        np.where(centred >= 0.02, "Bull", "Sideways"),
    ).astype(object)
    out[centred.isna().to_numpy()] = None
    return out


def benchmark_labels(frame):
    crisis = (frame["vix_level"] > 25) & (frame["drawdown_60d"] < -0.10)
    return np.where(crisis, "Crisis", np.where(frame["sharpe_60d"] > 0, "Bull", "Sideways")).astype(object)


def macro_f1(reference, predicted, labels=LABELS):
    """Macro-averaged F1 over `labels` on the days that have a reference label."""
    ref, pred = _aligned(reference, predicted)
    scores = []
    for lab in labels:
        tp = np.sum((pred == lab) & (ref == lab))
        fp = np.sum((pred == lab) & (ref != lab))
        fn = np.sum((pred != lab) & (ref == lab))
        denom = 2 * tp + fp + fn
        scores.append(2 * tp / denom if denom else 0.0)
    return float(np.mean(scores))


def confusion(reference, predicted, labels=LABELS):
    """Rows = reference label, columns = predicted label, as nested dicts of counts."""
    ref, pred = _aligned(reference, predicted)
    return {r: {p: int(np.sum((ref == r) & (pred == p))) for p in labels} for r in labels}


def _aligned(reference, predicted):
    ref = np.asarray(reference, dtype=object)
    pred = np.asarray(predicted, dtype=object)
    keep = np.array([r is not None for r in ref], dtype=bool)
    return ref[keep], pred[keep]


def score_periods(dates, confirmed, periods=REFERENCE_PERIODS):
    """A period is correct if its most frequent confirmed label is one of the expected ones."""
    dates = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    labels = pd.Series(list(confirmed))
    rows = []
    for p in periods:
        mask = (dates >= p.start) & (dates <= p.end)
        counts = labels[mask].value_counts()
        if counts.empty:
            rows.append({**_period_info(p), "top": None, "share": 0.0, "correct": False})
            continue
        top = counts.index[0]
        rows.append(
            {
                **_period_info(p),
                "top": top,
                "share": round(float(counts.iloc[0] / counts.sum()), 3),
                "shares": {k: round(float(v / counts.sum()), 3) for k, v in counts.items()},
                "correct": bool(top in p.expected),
            }
        )
    return rows


def _period_info(p):
    return {"start": p.start, "end": p.end, "expected": list(p.expected), "event": p.event}


def switches_per_year(confirmed):
    labels = list(confirmed)
    if len(labels) < 2:
        return 0.0
    changes = sum(1 for a, b in zip(labels, labels[1:], strict=False) if a != b)
    return changes / (len(labels) / TRADING_DAYS)


def transition_lag(dates, confirmed, reference, year=2020):
    """Trading days from the first reference Crisis day of `year` to the model's Crisis.

    0 if the confirmed label is already Crisis on that day; None if the model never shows
    Crisis in the rest of that year (or there is no reference Crisis that year).
    """
    dates = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    ref = pd.Series(list(reference))
    conf = pd.Series(list(confirmed))
    in_year = dates.dt.year == year
    starts = ref[in_year & (ref == "Crisis")].index
    if len(starts) == 0:
        return None
    start = starts[0]
    hits = conf[in_year & (conf.index >= start) & (conf == "Crisis")].index
    return int(hits[0] - start) if len(hits) else None


def check_gates(metrics, gates=GATES):
    """Return {gate: passed} for the metrics produced by trainer.evaluate()."""
    lag = metrics.get("transition_lag_2020")
    return {
        "periods": metrics["periods_correct"] >= gates["periods_correct_min"],
        "macro_f1": metrics["macro_f1"] >= gates["macro_f1_min"],
        "fidelity": metrics["surrogate_fidelity"] >= gates["fidelity_min"],
        "stability": metrics["switches_per_year_test"] < gates["switches_per_year_max"],
        "transition_lag": lag is not None and lag <= gates["transition_lag_max"],
    }
