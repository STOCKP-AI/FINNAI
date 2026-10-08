"""Name the HMM states (Bull / Sideways / Crisis) and confirm regime changes.

States are numbered arbitrarily by EM (state 0 in one fit can be state 2 in the next), so
names are assigned automatically from what the market was doing on the days each state
was most likely, using the training rows only:

    Crisis   = the highest-volatility state if its mean trailing 20-day return is negative,
               otherwise the state with the lowest mean trailing return
    Bull     = of the remaining states, the one with the highest mean trailing return
    Sideways = every other state (two of them if the model has 4 states)

Why trailing and not forward returns (the Build Plan sketch used forward 20-day returns):
a crash state is followed by the rebound, so its mean forward return was the highest of
all states and the COVID crash was named "Bull" (run C0, 2 of 6 reference periods).
Trailing returns describe the state itself and use no future data at all.
"""

import numpy as np
import pandas as pd

from marketmood_ml.model.config import CONFIRM_DAYS, LABEL_RETURN_DAYS


def state_statistics(states, close, volatility, n_states):
    """Mean trailing return and volatility per state (rows with a trailing return only)."""
    stats = pd.DataFrame(
        {
            "state": np.asarray(states),
            "ret": pd.Series(np.asarray(close, dtype=float)).pct_change(LABEL_RETURN_DAYS),
            "vol": np.asarray(volatility, dtype=float),
        }
    ).dropna()
    s = stats.groupby("state").agg(ret=("ret", "mean"), vol=("vol", "mean"), days=("ret", "size"))
    return s.reindex(range(n_states))  # states never visited get NaN rows


def make_label_map(states, close, volatility, n_states):
    """Return {state index: label} following the rule in the module docstring."""
    s = state_statistics(states, close, volatility, n_states).dropna()
    if len(s) < 2:
        raise ValueError("need at least two visited states to name them")
    top_vol = s["vol"].idxmax()
    crisis = top_vol if s.loc[top_vol, "ret"] < 0 else s["ret"].idxmin()
    bull = s.drop(index=crisis)["ret"].idxmax()
    return {k: ("Crisis" if k == crisis else "Bull" if k == bull else "Sideways") for k in range(n_states)}


def label_probabilities(probs, label_map, labels):
    """Sum state probabilities into label probabilities, columns in `labels` order."""
    out = np.zeros((len(probs), len(labels)))
    for state, name in label_map.items():
        out[:, labels.index(name)] += probs[:, state]
    return out


def confirm_labels(labels, days=CONFIRM_DAYS):
    """2-day rule: the shown label changes only after `days` consecutive days agree.

    The first day starts with its own label. A one-day flip never changes the confirmed
    label; a new label that holds for `days` days becomes confirmed on the last of them.
    """
    labels = list(labels)
    if not labels:
        return []
    confirmed = [labels[0]]
    for t in range(1, len(labels)):
        window = labels[max(0, t - days + 1) : t + 1]
        new = labels[t]
        if len(window) == days and all(lab == new for lab in window) and new != confirmed[-1]:
            confirmed.append(new)
        else:
            confirmed.append(confirmed[-1])
    return confirmed
