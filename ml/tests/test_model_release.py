"""Checks on every released model in ml/models/ against the real Yahoo snapshot (to 29 May 2026).

TC-ML-05 (reference periods), TC-ML-06 (metrics and confusion matrix recorded) and TC-ML-07
(surrogate fidelity) on real data. No network, no database.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketmood_ml.common import EXCLUDED_FEATURES
from marketmood_ml.model.artifacts import MODEL_FILES, MODELS_DIR, load_model, sha256_file
from marketmood_ml.model.config import GATES, LABELS
from marketmood_ml.model.evaluation import check_gates, score_periods
from marketmood_ml.model.explain import fidelity
from marketmood_ml.model.predict import daily_labels, predict_history, scaled_inputs, validate_output
from marketmood_ml.pipelines import ingest
from marketmood_ml.pipelines.features import compute_features

SNAPSHOT = Path(__file__).resolve().parents[1] / "pipelines" / "data"
RELEASED = sorted(p for p in MODELS_DIR.glob("*") if (p / "model.json").is_file())


@pytest.fixture(scope="module")
def real_frame():
    nifty = pd.read_csv(SNAPSHOT / "nifty.csv", parse_dates=["date"])
    vix = pd.read_csv(SNAPSHOT / "vix.csv", parse_dates=["date"]).rename(columns={"vix_close": "close"})
    market, _ = ingest.merge_market_data(nifty, vix)
    frame = compute_features(market).drop(columns="fii_flow").merge(market[["date", "close"]], on="date")
    return frame.reset_index(drop=True)


@pytest.fixture(scope="module", params=RELEASED, ids=lambda p: p.name)
def released(request):
    folder = request.param
    model = load_model(folder, {name: sha256_file(folder / name) for name in MODEL_FILES})
    return folder, model


def test_at_least_one_model_is_released():
    assert RELEASED, "no model folder in ml/models"


def test_files_are_clean_lf_text(released):
    """The pre-commit whitespace hooks must never change a file (that would break its checksum)."""
    folder, _ = released
    for path in folder.iterdir():
        data = path.read_bytes()
        assert b"\r" not in data, path
        assert data.endswith(b"\n") and not data.endswith(b"\n\n"), path
        assert all(line == line.rstrip() for line in data.decode("utf-8").split("\n")), path


def test_model_description_is_consistent(released):
    folder, model = released
    assert model.version == folder.name
    assert not set(model.features) & set(EXCLUDED_FEATURES)
    assert sorted(set(model.label_map.values())) == sorted(LABELS)
    np.testing.assert_allclose(model.hmm.transmat.sum(axis=1), 1.0)
    np.testing.assert_allclose(model.hmm.startprob.sum(), 1.0)


def test_reference_periods_on_the_real_snapshot(released, real_frame):
    """TC-ML-05: >= 5 of 6 reference periods correct with causal (filtered) labels."""
    _, model = released
    out = predict_history(model, real_frame)
    assert validate_output(out) == []
    periods = score_periods(real_frame["date"], out["confirmed_label"])
    assert sum(p["correct"] for p in periods) >= GATES["periods_correct_min"], periods


def test_surrogate_fidelity_on_the_real_snapshot(released, real_frame):
    """TC-ML-07: the explanations imitate the HMM on >= 95% of real days."""
    _, model = released
    x = scaled_inputs(model, real_frame)
    _, labels = daily_labels(model, x)
    assert fidelity(model.surrogate(), x, [LABELS.index(lab) for lab in labels]) >= GATES["fidelity_min"]


def test_metrics_record_the_gate_result(released):
    """TC-ML-06: macro-F1 and the confusion matrix are saved; the status follows the gates."""
    folder, _ = released
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["confusion"]) == set(LABELS)
    assert 0 <= metrics["macro_f1"] <= 1
    assert metrics["gates"] == check_gates(metrics)
    assert metrics["passed"] == all(metrics["gates"].values())
