"""Turn a released model + the feature history into one regime row per day.

Used by both training (to evaluate exactly what will be published) and mm-infer (to
publish it), so the two can never disagree.
"""

import numpy as np
import pandas as pd

from marketmood_ml.model.config import LABELS
from marketmood_ml.model.explain import contributions, surrogate_predict, top_signals
from marketmood_ml.model.hmm import filtered_probs, transform
from marketmood_ml.model.labeling import confirm_labels, label_probabilities

PROB_DECIMALS = 6  # stored precision; keeps reruns identical across machines


def scaled_inputs(model, frame):
    return model.scaler.apply(transform(frame, model.features, model.log_transform))


def daily_labels(model, x):
    """Label probabilities (T, 3) and daily labels from scaled inputs."""
    probs = filtered_probs(model.hmm, x)
    label_probs = label_probabilities(probs, model.label_map, LABELS)
    labels = [LABELS[i] for i in label_probs.argmax(axis=1)]
    return label_probs, labels


def predict_history(model, frame):
    """Return a DataFrame with the regime_output columns for every day in `frame`.

    confidence is the filtered probability of the label shown (confirmed_label), so on the
    day after a one-day flip it is low rather than borrowing the new label's probability.
    surrogate_agrees says whether the explanation model gives the HMM's label that day;
    when it is false the signals are a weaker explanation and the UI should say so.
    """
    x = scaled_inputs(model, frame)
    label_probs, labels = daily_labels(model, x)
    confirmed = confirm_labels(labels)
    confirmed_idx = np.array([LABELS.index(c) for c in confirmed])
    surrogate = model.surrogate()
    contrib = contributions(surrogate, x)
    agrees = surrogate_predict(surrogate, x) == np.array([LABELS.index(lab) for lab in labels])
    raw = frame[list(model.features)].to_numpy(dtype=float)
    signals = [
        top_signals(contrib[t, confirmed_idx[t]], raw[t], model.medians, model.features)
        for t in range(len(frame))
    ]
    rounded = np.round(label_probs, PROB_DECIMALS)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(frame["date"]).dt.date,
            "label": labels,
            "confidence": rounded[np.arange(len(frame)), confirmed_idx],
            "p_bull": rounded[:, 0],
            "p_sideways": rounded[:, 1],
            "p_crisis": rounded[:, 2],
            "confirmed_label": confirmed,
            "signals": signals,
            "surrogate_agrees": agrees.astype(bool),
            "model_version": model.version,
        }
    )


def validate_output(out):
    """Return a list of problems; empty means the rows may be written."""
    errors = []
    if out.empty:
        return ["no rows"]
    probs = out[["p_bull", "p_sideways", "p_crisis"]].to_numpy(dtype=float)
    if not np.isfinite(probs).all():
        errors.append("NaN or infinite probabilities")
    elif (probs < 0).any() or (probs > 1).any():
        errors.append("probabilities outside 0..1")
    elif np.abs(probs.sum(axis=1) - 1).max() > 1e-5:
        errors.append("probabilities do not sum to 1")
    if not set(out["label"]).issubset(LABELS) or not set(out["confirmed_label"]).issubset(LABELS):
        errors.append("unknown label")
    if out["date"].duplicated().any():
        errors.append("duplicate dates")
    return errors
