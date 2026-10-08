"""Synthetic data for the model tests: a market that really switches between three regimes."""

import numpy as np
import pandas as pd

from marketmood_ml.model.config import ModelConfig
from marketmood_ml.pipelines.features import compute_features

# (daily mean return, daily volatility, VIX level) per regime
REGIMES = {"calm_up": (0.0009, 0.006, 12.0), "choppy": (0.0, 0.011, 18.0), "crash": (-0.004, 0.03, 35.0)}
BLOCKS = ["calm_up", "choppy", "calm_up", "crash", "choppy", "calm_up", "choppy", "crash", "calm_up"]

FAST = ModelConfig("T", "test configuration", seeds=(0, 1), n_iter=100, covariance_type="diag")


def regime_market(n_blocks=None, block_days=110, seed=3):
    """Business-day market data (date, close, vix_close) with regimes in blocks."""
    rng = np.random.default_rng(seed)
    blocks = BLOCKS if n_blocks is None else (BLOCKS * 3)[:n_blocks]
    returns, vix, truth = [], [], []
    for name in blocks:
        mu, sigma, level = REGIMES[name]
        returns.append(rng.normal(mu, sigma, block_days))
        vix.append(np.clip(level + rng.normal(0, 1.5, block_days), 9, 90))
        truth += [name] * block_days
    r = np.concatenate(returns)
    dates = pd.bdate_range("2018-01-01", periods=len(r))
    return pd.DataFrame(
        {
            "date": dates,
            "close": 10000 * np.exp(np.cumsum(r)),
            "vix_close": np.concatenate(vix),
            "truth": truth,
        }
    )


def regime_frame(**kw):
    """Model input (date, 8 features, close) built with the real feature code."""
    market = regime_market(**kw)
    feats = compute_features(market[["date", "close", "vix_close"]])
    frame = feats.drop(columns="fii_flow").merge(market[["date", "close", "truth"]], on="date")
    return frame.reset_index(drop=True)
