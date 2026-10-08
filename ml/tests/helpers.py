"""Synthetic data and fakes shared by the pipeline tests. No network, no database."""

import argparse

import numpy as np
import pandas as pd

NIFTY_TICKER = "^NSEI"
VIX_TICKER = "^INDIAVIX"


def args(**kw):
    """Command-line arguments for ingest.run() without going through argparse."""
    base = {"full": False, "start": None, "dry_run": False}
    base.update(kw)
    return argparse.Namespace(**base)


def market_frame(n=200, start="2024-01-01", end=None, seed=7, with_fii=True):
    """Deterministic NIFTY-like daily data on business days (ending at `end` if given)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=n) if end else pd.bdate_range(start, periods=n)
    close = 20000 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n)))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vix = np.clip(15 + np.cumsum(rng.normal(0, 0.3, n)), 9, 40)
    df = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100_000, 500_000, n),
            "vix_close": vix,
        }
    )
    if with_fii:
        df["fii_flow"] = 0.0
    return df


def yfinance_frame(df, ticker, price_col="close"):
    """Shape of a yfinance 1.3.0 download(auto_adjust=False) result.

    Multi-level columns (Price, Ticker), alphabetical price order with "Adj Close"
    first, a "Date" index of datetime64[s]. "Adj Close" is deliberately different
    from "Close" so a test fails if the wrong column is picked.
    """
    index = pd.DatetimeIndex(df["date"].to_numpy(), name="Date").astype("datetime64[s]")
    close = df[price_col].to_numpy()
    data = {
        ("Adj Close", ticker): close * 0.5,
        ("Close", ticker): close,
        ("High", ticker): df["high"].to_numpy() if price_col == "close" else close * 1.01,
        ("Low", ticker): df["low"].to_numpy() if price_col == "close" else close * 0.99,
        ("Open", ticker): df["open"].to_numpy() if price_col == "close" else close,
        ("Volume", ticker): df["volume"].to_numpy() if price_col == "close" else np.zeros(len(df), dtype=int),
    }
    frame = pd.DataFrame(data, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Price", "Ticker"])
    return frame


class FakeYahoo:
    """Serves yfinance-shaped frames for NIFTY and VIX, filtered to the requested range."""

    def __init__(self, market, vix_missing=()):
        self.market = market
        self.vix_missing = {pd.Timestamp(d) for d in vix_missing}
        self.calls = []

    def __call__(self, ticker, start, end, **_):
        self.calls.append((ticker, start, end))
        m = self.market[(self.market["date"].dt.date >= start) & (self.market["date"].dt.date <= end)]
        if ticker == VIX_TICKER:
            m = m[~m["date"].isin(self.vix_missing)]
            return yfinance_frame(m, ticker, price_col="vix_close")
        return yfinance_frame(m, ticker)
