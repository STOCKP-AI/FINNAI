"""Train one configuration end to end, evaluate it, and pick the release from the sweep.

Steps for one configuration (Prototype Build Plan v2.1 section 7):
    1. split by time: train = dates up to 24 months before the last date, test = the rest
    2. transform + scale (scaler fitted on train only), fit the HMM over 10 seeds
    3. causal filtered probabilities for every day, automatic state names, 2-day rule
    4. surrogate (LightGBM) for explanations, fidelity
    5. evaluation: reference periods, macro-F1, stability, 2020 lag, benchmark, backtest
"""

import logging

import numpy as np
import pandas as pd

from marketmood_ml.common import MM_DATA_002, PipelineError
from marketmood_ml.model.artifacts import TrainedModel, normalise_text
from marketmood_ml.model.backtest import backtest
from marketmood_ml.model.config import CONFIGS, LABELS, REFERENCE_PERIODS, TEST_MONTHS, WALK_FORWARD_START
from marketmood_ml.model.evaluation import (
    benchmark_labels,
    check_gates,
    confusion,
    macro_f1,
    reference_labels,
    score_periods,
    switches_per_year,
    transition_lag,
)
from marketmood_ml.model.explain import fidelity, train_surrogate
from marketmood_ml.model.hmm import Scaler, filtered_probs, fit_best_hmm, transform
from marketmood_ml.model.labeling import confirm_labels, label_probabilities, make_label_map
from marketmood_ml.model.predict import predict_history

log = logging.getLogger("train")


def train_rows(dates, months=TEST_MONTHS):
    """Number of leading rows in the training period (dates <= last date - months)."""
    dates = pd.to_datetime(pd.Series(dates))
    cut = dates.max() - pd.DateOffset(months=months)
    n = int((dates <= cut).sum())
    if n < 250 or n >= len(dates):
        raise PipelineError(MM_DATA_002, f"not enough history to split: {n} training rows of {len(dates)}")
    return n


def model_version(frame, config):
    return f"hmm-{pd.Timestamp(frame['date'].max()):%Y%m%d}-{config.name.lower()}"


def train_config(frame, config, version=None):
    """Fit, name and explain one configuration; return (TrainedModel, daily output, metrics)."""
    frame = frame.reset_index(drop=True)
    n_train = train_rows(frame["date"])
    raw = transform(frame, config.features, config.log_transform)
    scaler = Scaler.fit(raw[:n_train])
    x = scaler.apply(raw)
    params, seed, loglik, logliks = fit_best_hmm(x[:n_train], config)

    states = filtered_probs(params, x).argmax(axis=1)
    label_map = make_label_map(
        states[:n_train], frame["close"][:n_train], frame["volatility_20d"][:n_train], config.n_states
    )
    label_probs = label_probabilities(filtered_probs(params, x), label_map, LABELS)
    label_idx = label_probs.argmax(axis=1)

    booster = train_surrogate(x, label_idx)
    oos_booster = train_surrogate(x[:n_train], label_idx[:n_train])
    dates = pd.to_datetime(frame["date"])
    model = TrainedModel(
        version=version or model_version(frame, config),
        config=config.to_dict(),
        features=list(config.features),
        log_transform=config.log_transform,
        scaler=scaler,
        hmm=params,
        label_map=label_map,
        medians=[float(v) for v in np.median(frame[list(config.features)].to_numpy()[:n_train], axis=0)],
        train={
            "start": str(dates.iloc[0].date()),
            "end": str(dates.iloc[n_train - 1].date()),
            "rows": n_train,
            "test_start": str(dates.iloc[n_train].date()),
            "test_end": str(dates.iloc[-1].date()),
            "test_rows": len(frame) - n_train,
        },
        seed=seed,
        log_likelihood=loglik,
        surrogate_text=normalise_text(booster.model_to_string()),
    )
    surrogate = model.surrogate()  # the normalised text, exactly as it will be loaded later
    out = predict_history(model, frame)
    if [LABELS.index(lab) for lab in out["label"]] != label_idx.tolist():
        raise RuntimeError("published labels differ from training labels")  # pragma: no cover

    metrics = evaluate(frame, out, n_train)
    metrics.update(
        {
            "seed": seed,
            "log_likelihood": round(loglik, 3),
            "log_likelihood_by_seed": {str(k): round(v, 3) for k, v in logliks.items()},
            "surrogate_fidelity": round(fidelity(surrogate, x, label_idx), 4),
            "surrogate_fidelity_test": round(fidelity(oos_booster, x[n_train:], label_idx[n_train:]), 4),
            "state_days": {f"{k}:{label_map[k]}": int(np.sum(states[:n_train] == k)) for k in label_map},
        }
    )
    metrics["gates"] = check_gates(metrics)
    metrics["passed"] = all(metrics["gates"].values())
    model.metrics = metrics
    return model, out, metrics


def evaluate(frame, out, n_train):
    dates = pd.to_datetime(frame["date"]).reset_index(drop=True)
    confirmed = list(out["confirmed_label"])
    ref = reference_labels(frame["close"], frame["vix_level"])
    bench = benchmark_labels(frame)
    periods = score_periods(dates, confirmed)
    bt_all, _ = backtest(frame["close"], confirmed)
    bt_test, _ = backtest(frame["close"][n_train:], confirmed[n_train:])
    last = out.iloc[-1]
    return {
        "periods": periods,
        "periods_correct": sum(p["correct"] for p in periods),
        "macro_f1": round(macro_f1(ref, confirmed), 4),
        "macro_f1_test": round(macro_f1(ref[n_train:], confirmed[n_train:]), 4),
        "macro_f1_benchmark": round(macro_f1(ref, bench), 4),
        "confusion": confusion(ref, confirmed),
        "confusion_benchmark": confusion(ref, bench),
        "switches_per_year_test": round(switches_per_year(confirmed[n_train:]), 2),
        "switches_per_year_all": round(switches_per_year(confirmed), 2),
        "transition_lag_2020": transition_lag(dates, confirmed, ref, 2020),
        "label_days": {lab: int(sum(c == lab for c in confirmed)) for lab in LABELS},
        "mean_confidence": round(float(out["confidence"].mean()), 4),
        "backtest_all": bt_all,
        "backtest_test": bt_test,
        "latest": {
            "date": str(last["date"]),
            "label": last["label"],
            "confirmed_label": last["confirmed_label"],
            "confidence": float(last["confidence"]),
        },
    }


def fit_and_label(frame, config, n_fit, n_upto):
    """Fit scaler, HMM and state names on rows [0, n_fit); label rows [0, n_upto) causally."""
    raw = transform(frame.iloc[:n_upto], config.features, config.log_transform)
    scaler = Scaler.fit(raw[:n_fit])
    x = scaler.apply(raw)
    params, _, _, _ = fit_best_hmm(x[:n_fit], config)
    probs = filtered_probs(params, x)
    label_map = make_label_map(
        probs.argmax(axis=1)[:n_fit], frame["close"][:n_fit], frame["volatility_20d"][:n_fit], config.n_states
    )
    return [LABELS[i] for i in label_probabilities(probs, label_map, LABELS).argmax(axis=1)]


def walk_forward(frame, config, start_year=WALK_FORWARD_START):
    """Fully out-of-sample check: for each year Y, refit on the days before Y and label Y.

    Unlike the main evaluation (whose reference periods fall inside the training window),
    no day here was seen by the model that labels it. Reported, not used for selection.
    """
    frame = frame.reset_index(drop=True)
    dates = pd.to_datetime(frame["date"])
    raw_labels, first = [], None
    for year in range(start_year, dates.iloc[-1].year + 1):
        n_fit = int((dates < pd.Timestamp(year, 1, 1)).sum())
        n_upto = int((dates <= pd.Timestamp(year, 12, 31)).sum())
        if n_fit < 250 or n_upto <= n_fit:
            continue
        first = n_fit if first is None else first
        raw_labels += fit_and_label(frame, config, n_fit, n_upto)[n_fit:n_upto]
    if first is None:
        return None
    confirmed = confirm_labels(raw_labels)
    oos_dates = dates.iloc[first:].reset_index(drop=True)
    ref = reference_labels(frame["close"], frame["vix_level"])[first:]
    periods = [p for p in REFERENCE_PERIODS if pd.Timestamp(p.start) >= oos_dates.iloc[0]]
    scored = score_periods(oos_dates, confirmed, periods)
    return {
        "start": str(oos_dates.iloc[0].date()),
        "end": str(oos_dates.iloc[-1].date()),
        "periods": scored,
        "periods_correct": sum(p["correct"] for p in scored),
        "periods_scored": len(scored),
        "macro_f1": round(macro_f1(ref, confirmed), 4),
        "switches_per_year": round(switches_per_year(confirmed), 2),
        "transition_lag_2020": transition_lag(oos_dates, confirmed, ref, 2020),
        "label_days": {lab: int(sum(c == lab for c in confirmed)) for lab in LABELS},
    }


def run_sweep(frame, configs=CONFIGS):
    """Train every configuration; return a list of (config, model, out, metrics)."""
    results = []
    for config in configs:
        model, out, metrics = train_config(frame, config)
        log.info(
            "%s: periods %d/6, macro-F1 %.3f, fidelity %.3f, switches/yr %.1f, lag %s -> %s",
            config.name,
            metrics["periods_correct"],
            metrics["macro_f1"],
            metrics["surrogate_fidelity"],
            metrics["switches_per_year_test"],
            metrics["transition_lag_2020"],
            "PASS"
            if metrics["passed"]
            else "fail: " + ", ".join(k for k, v in metrics["gates"].items() if not v),
        )
        results.append((config, model, out, metrics))
    return results


def select(results):
    """Pre-registered rule: first config passing every gate, else most periods then macro-F1."""
    for result in results:
        if result[3]["passed"]:
            return result
    return max(results, key=lambda r: (r[3]["periods_correct"], r[3]["macro_f1"]))
