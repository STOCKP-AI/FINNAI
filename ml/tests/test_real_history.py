"""Regression tests on a real Yahoo Finance snapshot (NIFTY 50 + India VIX, to 29 May 2026).

ml/pipelines/data/ holds the CSVs the Phase 2 pipeline saved:
nifty.csv and vix.csv (raw downloads) and market_data.csv (after the old inner join).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from marketmood_ml.common import FEATURE_COLUMNS
from marketmood_ml.pipelines import ingest
from marketmood_ml.pipelines.features import compute_features

SNAPSHOT = Path(__file__).resolve().parents[1] / "pipelines" / "data"

# Values stored in Supabase's features table (computed by the Phase 2 code), read on 7 Oct 2026.
# Columns: volatility_20d, sharpe_60d, autocorr_lag1, vix_change_30d, drawdown_60d, skewness_30d, bb_width
STORED = {
    "2018-10-05": [0.0108688790313014, -0.0829220476894317, 0.29868790440135, 0.514198000504281,
                   -0.121144081840738, -0.435724493160839, 0.117516708457663],
    "2020-03-23": [0.0424880238265802, -0.2751565696416, -0.455120685918942, 4.2242379723361,
                   -0.384398524527421, -1.23332681201615, 0.519300880536901],
    "2021-05-04": [0.0126743481514602, 0.0783169955951837, -0.109929078208581, 0.141369067611156,
                   -0.0533485390224191, -0.62491502546436, 0.0533446239746559],
    "2022-06-17": [0.0106493311521969, -0.166240301192707, 0.00772265462303087, 0.07105883430032,
                   -0.152874269163066, 0.361713539175153, 0.103330623734363],
    "2024-06-04": [0.0168893630201916, -0.0260192253436909, -0.521382725743601, 0.987369979508752,
                   -0.0592935994164107, -2.19398917529089, 0.0668627126735841],
    "2026-05-29": [0.00856200374923215, -0.0956630950265296, 0.0392705198705562, -0.132833397541613,
                   -0.0764338987641864, -0.210546848791364, 0.0469245891197113],
}  # fmt: skip


def read(name):
    return pd.read_csv(SNAPSHOT / f"{name}.csv", parse_dates=["date"])


def test_left_join_recovers_the_17_days_the_inner_join_dropped():
    nifty = read("nifty")
    vix = read("vix").rename(columns={"vix_close": "close"})
    merged, report = ingest.merge_market_data(nifty, vix)
    assert len(merged) == len(nifty) == 2464
    assert len(report["vix_filled"]) == 17
    assert report["dropped_no_vix"] == [] and report["dropped_no_price"] == []
    assert len(read("market_data")) == 2464 - 17
    errors, warnings = ingest.validate(merged)
    assert errors == []
    assert ingest.rows_per_year(merged)[2021] == 248  # was 238 with the inner join


def test_features_match_values_stored_in_supabase():
    """Formulas unchanged: same input as Phase 2 gives the values already in the database."""
    f = compute_features(read("market_data")).set_index("date")
    cols = [c for c in FEATURE_COLUMNS if c != "vix_level"]
    for day, expected in STORED.items():
        np.testing.assert_allclose(f.loc[day, cols].to_numpy(float), expected, rtol=1e-12, err_msg=day)


def test_warmup_and_last_day_on_real_data():
    market = read("market_data")
    f = compute_features(market)
    assert len(f) == len(market) - 60
    assert f["date"].iloc[0] == market["date"].iloc[60]
    assert f["date"].iloc[-1] == pd.Timestamp("2026-05-29")
    assert not f[FEATURE_COLUMNS].isna().any().any()
    assert (f["drawdown_60d"] <= 0).all()
