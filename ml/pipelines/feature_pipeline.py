"""Compute the 8 model features from market_data and upsert them into features.

Usage (run from the repository root, ml/ or ml/pipelines/):
    python ml/pipelines/feature_pipeline.py            # recompute all dates and upsert
    python ml/pipelines/feature_pipeline.py --dry-run  # compute and check, write nothing

Feature definitions are unchanged from Phase 2 (the audit confirmed them; a test compares
against the old code and spot checks match the values stored in Supabase to 1e-14).
Values do change on dates whose rolling windows include days that were previously
missing, once `ingest.py --full` has filled the 17 days the old inner join dropped.
What changed in Phase 2.5:
- The calculation is a pure function, compute_features(), so it can be unit-tested.
- Rows are dropped only when a model feature is missing (warm-up period: first 60 rows),
  not because of fii_flow.
- A check blocks the write if any feature is NaN or infinite, or drawdown is positive.
- fii_flow is still copied into the features table but is listed in EXCLUDED_FEATURES
  and must not be used for training.

Definitions (window lengths in trading days):
    returns         close.pct_change()
    volatility_20d  20-day standard deviation of returns
    sharpe_60d      60-day mean of returns / 60-day std of returns (not annualised)
    autocorr_lag1   30-day rolling lag-1 autocorrelation of returns
    vix_level       India VIX close
    vix_change_30d  percentage change of VIX over 30 trading days (e.g. 0.25 = +25%)
    drawdown_60d    (close - rolling 60-day max) / rolling max = close / max - 1 (<= 0)
    skewness_30d    30-day rolling skewness of returns
    bb_width        (upper - lower Bollinger band) / 20-day mean = 4 * std20 / mean20
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):  # allow "python ml/pipelines/feature_pipeline.py"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.common import (  # noqa: E402
    FEATURE_COLUMNS,
    MM_DATA_002,
    MM_DB_001,
    PipelineError,
    db_connection,
    describe_database_url,
    is_database_error,
    load_settings,
    setup_logging,
)

log = setup_logging("features")

WARMUP_ROWS = 60  # the longest window (60-day Sharpe on returns) needs 61 prices

UPSERT_SQL = """
INSERT INTO features (
    date, volatility_20d, sharpe_60d, autocorr_lag1, vix_level, vix_change_30d,
    drawdown_60d, skewness_30d, bb_width, fii_flow
)
VALUES %s
ON CONFLICT (date) DO UPDATE SET
    volatility_20d = EXCLUDED.volatility_20d,
    sharpe_60d = EXCLUDED.sharpe_60d,
    autocorr_lag1 = EXCLUDED.autocorr_lag1,
    vix_level = EXCLUDED.vix_level,
    vix_change_30d = EXCLUDED.vix_change_30d,
    drawdown_60d = EXCLUDED.drawdown_60d,
    skewness_30d = EXCLUDED.skewness_30d,
    bb_width = EXCLUDED.bb_width,
    fii_flow = EXCLUDED.fii_flow;
"""


def compute_features(market):
    """Return a frame with date, the 8 features and fii_flow; warm-up rows removed.

    `market` needs columns date, close, vix_close (fii_flow optional), one row per
    trading day. It is sorted by date here.
    """
    df = market.sort_values("date").reset_index(drop=True).copy()
    returns = df["close"].pct_change()

    out = pd.DataFrame({"date": df["date"]})
    out["volatility_20d"] = returns.rolling(20).std()
    out["sharpe_60d"] = returns.rolling(60).mean() / returns.rolling(60).std()
    out["autocorr_lag1"] = returns.rolling(30).apply(lambda x: x.autocorr(lag=1), raw=False)
    out["vix_level"] = df["vix_close"]
    out["vix_change_30d"] = df["vix_close"].pct_change(30)
    rolling_max = df["close"].rolling(60).max()
    out["drawdown_60d"] = (df["close"] - rolling_max) / rolling_max  # = close / max - 1
    out["skewness_30d"] = returns.rolling(30).skew()
    mean20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    out["bb_width"] = ((mean20 + 2 * std20) - (mean20 - 2 * std20)) / mean20
    out["fii_flow"] = df["fii_flow"].fillna(0.0) if "fii_flow" in df else 0.0

    out[FEATURE_COLUMNS] = out[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
    return out.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)


def validate_features(features):
    """Return a list of errors; an empty list means the frame may be written."""
    errors = []
    if features.empty:
        return ["no feature rows"]
    values = features[FEATURE_COLUMNS]
    if values.isna().any().any() or np.isinf(values.to_numpy(dtype=float)).any():
        errors.append("NaN or infinite feature values")
    if (features["drawdown_60d"] > 1e-12).any():
        errors.append("positive drawdown_60d values")
    if features["date"].duplicated().any():
        errors.append("duplicate dates")
    return errors


def to_rows(features):
    cols = ["date", *FEATURE_COLUMNS, "fii_flow"]
    rows = []
    for r in features[cols].itertuples(index=False):
        d = r[0].date() if hasattr(r[0], "date") else r[0]
        rows.append((d, *[float(v) for v in r[1:]]))
    return rows


def load_market_data(conn):
    return pd.read_sql(
        "SELECT date, close, vix_close, fii_flow FROM market_data ORDER BY date;",
        conn,
        parse_dates=["date"],
    )


def upsert(conn, rows):
    from psycopg2.extras import execute_values

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)


def run(args):
    url = load_settings()
    log.info("Database: %s", describe_database_url(url))
    with db_connection(url) as conn:
        market = load_market_data(conn)
        log.info("Loaded %d market_data rows (%s to %s).", len(market),
                 market["date"].min().date() if len(market) else "-",
                 market["date"].max().date() if len(market) else "-")
        features = compute_features(market)
        errors = validate_features(features)
        if errors:
            raise PipelineError(MM_DATA_002, "feature check failed, nothing written: " + "; ".join(errors))
        log.info("Computed %d feature rows (%s to %s); %d warm-up rows dropped.",
                 len(features), features["date"].iloc[0].date(), features["date"].iloc[-1].date(),
                 len(market) - len(features))
        if args.dry_run:
            log.info("Dry run: nothing written.")
            return 0
        upsert(conn, to_rows(features))
    log.info("Upserted %d rows into features.", len(features))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Compute features from market_data.")
    p.add_argument("--dry-run", action="store_true", help="compute and check, but write nothing")
    args = p.parse_args(argv)
    try:
        return run(args)
    except PipelineError as exc:
        log.error("%s", exc)
        return 1
    except Exception as exc:
        if is_database_error(exc):
            log.error("%s: database error: %s", MM_DB_001, exc)
            return 1
        log.exception("Unexpected error")
        return 2


if __name__ == "__main__":
    sys.exit(main())
