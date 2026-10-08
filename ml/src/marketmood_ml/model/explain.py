"""Explain each day's label with a surrogate model and TreeSHAP.

The HMM itself is hard to explain feature by feature, so a small LightGBM classifier (the
surrogate) is trained to imitate the HMM's label from the same scaled inputs. If it agrees
with the HMM on at least 95% of days (fidelity), its exact TreeSHAP contributions are a
faithful account of which features pushed today towards the label shown.

LightGBM computes TreeSHAP itself (predict(pred_contrib=True)); the shap package is not needed.
"""

import numpy as np

from marketmood_ml.common import MM_CONFIG_002, PipelineError
from marketmood_ml.model.config import LABELS, SURROGATE_PARAMS, SURROGATE_ROUNDS, TOP_SIGNALS


def _lightgbm():
    """Import LightGBM with a clear message if its native library cannot be loaded."""
    try:
        import lightgbm
    except (ImportError, OSError) as exc:  # pragma: no cover - depends on the machine
        raise PipelineError(
            MM_CONFIG_002,
            f"LightGBM could not be loaded ({exc}). Windows: install the Microsoft Visual C++ "
            "Redistributable (x64). macOS: run `brew install libomp`. Then `uv sync` again.",
        ) from exc
    return lightgbm


def train_surrogate(x, label_idx, params=SURROGATE_PARAMS, rounds=SURROGATE_ROUNDS):
    """Train the surrogate on scaled inputs and integer labels (index into LABELS)."""
    lgb = _lightgbm()
    data = lgb.Dataset(x, label=np.asarray(label_idx), free_raw_data=False)
    return lgb.train(dict(params), data, num_boost_round=rounds)


def load_surrogate(text):
    return _lightgbm().Booster(model_str=text)


def surrogate_predict(booster, x):
    return np.asarray(booster.predict(x)).reshape(len(x), len(LABELS)).argmax(axis=1)


def fidelity(booster, x, label_idx):
    """Share of days on which the surrogate's label equals the HMM's label."""
    return float(np.mean(surrogate_predict(booster, x) == np.asarray(label_idx)))


def contributions(booster, x):
    """TreeSHAP values, shape (T, n_labels, n_features); the bias term is dropped."""
    raw = np.asarray(booster.predict(x, pred_contrib=True))
    n_features = x.shape[1]
    return raw.reshape(len(x), len(LABELS), n_features + 1)[:, :, :n_features]


def top_signals(contrib_row, raw_values, medians, features, k=TOP_SIGNALS):
    """Top-k features by absolute contribution towards one label, for one day.

    contrib_row: contributions towards the label shown (n_features,).
    direction: whether today's raw value is above ("up") or below ("down") the
    training median, so the UI can say "VIX is high" rather than quote a z-score.
    """
    order = np.argsort(-np.abs(contrib_row), kind="stable")[:k]
    return [
        {
            "feature": features[i],
            "value": _sig(raw_values[i], 6),
            "contribution": _sig(contrib_row[i], 4),
            "direction": "up" if raw_values[i] > medians[i] else "down",
        }
        for i in order
    ]


def _sig(value, digits):
    """Round to significant digits; keeps JSON short and identical across machines."""
    return float(f"{float(value):.{digits}g}")
