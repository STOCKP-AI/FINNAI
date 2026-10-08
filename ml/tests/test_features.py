"""Unit tests for marketmood_ml.pipelines.features (TC-DATA-04, TC-DATA-05, regression).

Run from the repository root:  uv run pytest
"""

import unittest

import numpy as np
import pandas as pd

from marketmood_ml.common import EXCLUDED_FEATURES, FEATURE_COLUMNS
from marketmood_ml.pipelines.features import WARMUP_ROWS, compute_features, to_rows, validate_features
from tests.helpers import market_frame


def phase2_features(df):
    """The Phase 2 feature code, copied verbatim, to prove the refactor changes no values."""
    df = df.copy()
    df["returns"] = df["close"].pct_change()
    df["volatility_20d"] = df["returns"].rolling(20).std()
    df["sharpe_60d"] = df["returns"].rolling(60).mean() / df["returns"].rolling(60).std()
    df["autocorr_lag1"] = df["returns"].rolling(30).apply(lambda x: x.autocorr(lag=1), raw=False)
    df["vix_level"] = df["vix_close"]
    df["vix_change_30d"] = df["vix_close"].pct_change(30)
    rolling_max = df["close"].rolling(60).max()
    df["drawdown_60d"] = (df["close"] - rolling_max) / rolling_max
    df["skewness_30d"] = df["returns"].rolling(30).skew()
    rolling_mean = df["close"].rolling(20).mean()
    rolling_std = df["close"].rolling(20).std()
    df["bb_width"] = ((rolling_mean + 2 * rolling_std) - (rolling_mean - 2 * rolling_std)) / rolling_mean
    df.dropna(inplace=True)
    return df.reset_index(drop=True)


class TestDrawdown(unittest.TestCase):
    """TC-DATA-04: drawdown_60d on a hand-made series equals close / rolling max - 1."""

    def test_hand_made_series(self):
        n = 130
        close = np.full(n, 100.0)
        close[70] = 120.0  # new peak
        close[80] = 90.0  # 25% below the 120 peak
        market = pd.DataFrame(
            {
                "date": pd.bdate_range("2024-01-01", periods=n),
                "close": close + np.linspace(0, 0.5, n),  # tiny trend so std is never 0
                "vix_close": np.linspace(12, 18, n),
            }
        )
        f = compute_features(market).set_index("date")
        c = market.set_index("date")["close"]
        expected = c / c.rolling(60).max() - 1
        np.testing.assert_allclose(f["drawdown_60d"], expected.loc[f.index], rtol=1e-12, atol=1e-12)
        d80 = market["date"][80]
        self.assertAlmostEqual(f.loc[d80, "drawdown_60d"], c[d80] / c.iloc[21:81].max() - 1)
        self.assertLess(f.loc[d80, "drawdown_60d"], -0.2)
        self.assertTrue((f["drawdown_60d"] <= 0).all())


class TestWarmup(unittest.TestCase):
    """TC-DATA-05: no NaN after the warm-up period; the first 60 rows are dropped."""

    def test_first_60_rows_dropped_and_no_nan(self):
        market = market_frame(200)
        f = compute_features(market)
        self.assertEqual(WARMUP_ROWS, 60)
        self.assertEqual(len(f), 200 - 60)
        self.assertEqual(f["date"].iloc[0], market["date"].iloc[60])
        self.assertFalse(f[FEATURE_COLUMNS].isna().any().any())
        self.assertEqual(validate_features(f), [])

    def test_missing_fii_flow_does_not_drop_rows(self):
        market = market_frame(120)
        market["fii_flow"] = np.nan
        self.assertEqual(len(compute_features(market)), 60)


class TestUnchangedDefinitions(unittest.TestCase):
    """Refactor safety: values equal the Phase 2 code on the same data."""

    def test_matches_phase2_code(self):
        market = market_frame(300, seed=11)
        new = compute_features(market)
        old = phase2_features(market)
        self.assertEqual(len(new), len(old))
        for col in FEATURE_COLUMNS:
            np.testing.assert_allclose(new[col].to_numpy(), old[col].to_numpy(), rtol=1e-12, err_msg=col)


class TestValidationAndRows(unittest.TestCase):
    def test_positive_drawdown_is_rejected(self):
        f = compute_features(market_frame(100))
        f.loc[3, "drawdown_60d"] = 0.05
        self.assertIn("positive drawdown_60d values", validate_features(f))

    def test_infinite_value_is_rejected(self):
        f = compute_features(market_frame(100))
        f.loc[2, "bb_width"] = np.inf
        self.assertIn("NaN or infinite feature values", validate_features(f))

    def test_rows_have_date_8_features_and_fii_flow(self):
        rows = to_rows(compute_features(market_frame(70)))
        self.assertEqual(len(rows[0]), 1 + len(FEATURE_COLUMNS) + 1)
        self.assertEqual(type(rows[0][0]).__name__, "date")

    def test_fii_flow_is_never_a_model_feature(self):
        self.assertEqual(EXCLUDED_FEATURES, ["fii_flow"])
        self.assertNotIn("fii_flow", FEATURE_COLUMNS)


if __name__ == "__main__":
    unittest.main()
