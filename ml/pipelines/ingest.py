"""Download NIFTY 50 and India VIX daily prices from Yahoo Finance into market_data.

Usage (run from the repository root, ml/ or ml/pipelines/):
    python ml/pipelines/ingest.py                    # incremental: last stored date - 5 days -> today
    python ml/pipelines/ingest.py --full             # reload the last 10 years
    python ml/pipelines/ingest.py --start 2024-01-01 # reload from a given date
    python ml/pipelines/ingest.py --dry-run          # download and check, write nothing

Exit codes: 0 = success (including "no new trading day"), 1 = known failure (MM-* code
in the log, including database connection errors), 2 = unexpected error or bad
command-line arguments.

What changed in Phase 2.5 (audit findings A7-A10):
- Incremental by default instead of re-downloading 10 years every run.
- auto_adjust=False is explicit and columns are picked by exact name, so a yfinance
  default change cannot silently switch "Close" to "Adj Close".
- NIFTY days with no VIX value are forward-filled for at most 2 days (only between two
  real VIX values) instead of being dropped silently by an inner join; anything still
  missing is logged by date.
- The NSE website scraper is removed. fii_flow is not written (the column keeps its
  default of 0) and is excluded from modelling until a permitted source exists.
- 3 retries with backoff, then MM-DATA-003. Data-quality gate before any write
  (MM-DATA-002). Nothing runs on import, so the functions can be unit-tested.
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

if __package__ in (None, ""):  # allow "python ml/pipelines/ingest.py"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.common import (  # noqa: E402
    MM_DATA_002,
    MM_DATA_003,
    MM_DB_001,
    PipelineError,
    db_connection,
    describe_database_url,
    is_database_error,
    load_settings,
    setup_logging,
)

log = setup_logging("ingest")

NIFTY_TICKER = "^NSEI"
VIX_TICKER = "^INDIAVIX"
OVERLAP_DAYS = 5          # re-fetch this many calendar days to absorb late corrections
FULL_HISTORY_DAYS = 3653  # about 10 years
VIX_FFILL_LIMIT = 2       # forward-fill at most 2 consecutive missing VIX days
RETRIES = 3               # retries after the first attempt
MAX_DAILY_MOVE = 0.15     # warn when the close moves more than 15% in a day
MAX_GAP_DAYS = 5          # warn when consecutive rows are more than 5 calendar days apart
IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_BUFFER = (16, 0)  # NSE closes 15:30 IST; treat today's bar as final after 16:00

OHLCV = ["open", "high", "low", "close", "volume"]

UPSERT_SQL = """
INSERT INTO market_data (date, open, high, low, close, volume, vix_close)
VALUES %s
ON CONFLICT (date) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    vix_close = EXCLUDED.vix_close;
"""


# --------------------------------------------------------------------------- download

def download(ticker, start, end, retries=RETRIES, sleep=time.sleep):
    """Download daily bars for [start, end] (both inclusive).

    yfinance does not raise on network errors; it prints a message and returns an empty
    frame. An empty frame is therefore treated as a failure and retried.
    """
    last_error = "unknown error"
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            raw = yf.download(
                ticker,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # yfinance's end is exclusive
                interval="1d",
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
                timeout=30,
            )
            if raw is not None and not raw.empty:
                return raw
            last_error = "empty response"
        except Exception as exc:  # network errors, JSON errors, rate limits
            last_error = repr(exc)
        if attempt < attempts:
            wait = 2 ** attempt
            log.warning("%s download failed (attempt %d of %d): %s. Retrying in %d s.",
                        ticker, attempt, attempts, last_error, wait)
            sleep(wait)
    raise PipelineError(MM_DATA_003, f"{ticker} download failed after {attempts} attempts: {last_error}")


def normalise(raw, ticker):
    """Turn a yfinance frame into columns date, open, high, low, close, volume.

    Handles the (Price, Ticker) multi-level columns of yfinance 0.2.48+ and picks
    columns by exact name, so "Adj Close" can never be mistaken for "Close".
    """
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        level = next((i for i in range(df.columns.nlevels)
                      if ticker in df.columns.get_level_values(i)), None)
        if level is not None:
            df = df.xs(ticker, axis=1, level=level)
        else:
            df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise PipelineError(MM_DATA_003, f"{ticker}: unexpected columns {list(df.columns)}; missing {missing}")
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    out = df[OHLCV].copy()
    out.insert(0, "date", index.normalize())
    return out.reset_index(drop=True).sort_values("date").drop_duplicates("date", keep="last")


# ---------------------------------------------------------------------------- combine

def merge_market_data(nifty, vix):
    """Left-join VIX onto NIFTY trading days, forward-fill short VIX gaps.

    Returns (frame, report) where report lists the dates that were filled or dropped.
    """
    vix = vix[["date", "close"]].rename(columns={"close": "vix_close"})
    df = nifty.merge(vix, on="date", how="left").sort_values("date").reset_index(drop=True)

    bad_price = df[["open", "high", "low", "close"]].isna().any(axis=1)
    dropped_price = [d.date() for d in df.loc[bad_price, "date"]]
    df = df[~bad_price].reset_index(drop=True)

    was_missing = df["vix_close"].isna()
    # "inside" fills only gaps between two real VIX values. A missing VIX on the newest
    # day (Yahoo's VIX bar sometimes lags NIFTY) is NOT filled with yesterday's value;
    # that day is skipped tonight and picked up by tomorrow's 5-day overlap.
    df["vix_close"] = df["vix_close"].ffill(limit=VIX_FFILL_LIMIT, limit_area="inside")
    filled = [d.date() for d in df.loc[was_missing & df["vix_close"].notna(), "date"]]
    still_missing = df["vix_close"].isna()
    dropped_vix = [d.date() for d in df.loc[still_missing, "date"]]
    df = df[~still_missing].reset_index(drop=True)

    report = {"vix_filled": filled, "dropped_no_vix": dropped_vix, "dropped_no_price": dropped_price}
    return df, report


def drop_unfinished_session(df, now_ist):
    """Remove today's bar if the run happens before the session is final (16:00 IST).

    Known limitation: on the Diwali Muhurat evening session a run between 16:00 and the
    end of that session could store a partial bar; the next run's overlap corrects it.
    """
    today = now_ist.date()
    if df.empty or df["date"].iloc[-1].date() != today:
        return df
    if (now_ist.hour, now_ist.minute) >= MARKET_CLOSE_BUFFER:
        return df
    return df.iloc[:-1].reset_index(drop=True)


# ---------------------------------------------------------------------------- quality

def validate(df):
    """Data-quality gate. Returns (errors, warnings); any error blocks the write."""
    errors, warnings = [], []
    if df.empty:
        return ["no rows to write"], warnings
    if df["date"].duplicated().any():
        errors.append(f"duplicate dates: {sorted(set(df.loc[df['date'].duplicated(), 'date'].dt.date))[:5]}")
    prices = df[["open", "high", "low", "close"]]
    if prices.isna().any().any() or df["vix_close"].isna().any():
        errors.append("missing price or VIX values")
    nonpositive = df.loc[(prices <= 0).any(axis=1), "date"]
    if len(nonpositive):
        errors.append(f"price <= 0 on {[d.date().isoformat() for d in nonpositive[:5]]}")
    vix_bad = df.loc[(df["vix_close"] < 5) | (df["vix_close"] > 100), "date"]
    if len(vix_bad):
        errors.append(f"VIX outside 5-100 on {[d.date().isoformat() for d in vix_bad[:5]]}")

    tol = 1e-6
    hi_bad = df["high"] < df[["open", "close"]].max(axis=1) * (1 - tol)
    lo_bad = df["low"] > df[["open", "close"]].min(axis=1) * (1 + tol)
    if (hi_bad | lo_bad).any():
        warnings.append(f"high/low inconsistent with open/close on {int((hi_bad | lo_bad).sum())} rows")
    moves = df["close"].pct_change().abs()
    big = df.loc[moves > MAX_DAILY_MOVE, "date"]
    if len(big):
        warnings.append(f"daily move > {MAX_DAILY_MOVE:.0%} on {[d.date().isoformat() for d in big[:5]]}")
    gaps = df["date"].diff().dt.days
    wide = df.loc[gaps > MAX_GAP_DAYS, "date"]
    if len(wide):
        warnings.append(f"gap > {MAX_GAP_DAYS} days before {[d.date().isoformat() for d in wide[:5]]}")
    weekend = df.loc[df["date"].dt.dayofweek >= 5, "date"]
    if len(weekend):
        warnings.append(f"weekend rows (special sessions?) on {[d.date().isoformat() for d in weekend[:5]]}")
    zero_vol = int((df["volume"].fillna(0) <= 0).sum())
    if zero_vol:
        warnings.append(f"{zero_vol} rows with zero or missing volume (index volume is not used)")
    return errors, warnings


def rows_per_year(df):
    return df.groupby(df["date"].dt.year).size().to_dict()


# ------------------------------------------------------------------------------ write

def to_rows(df):
    rows = []
    for r in df.itertuples(index=False):
        volume = None if pd.isna(r.volume) else int(r.volume)
        rows.append((r.date.date(), float(r.open), float(r.high), float(r.low),
                     float(r.close), volume, float(r.vix_close)))
    return rows


def get_last_date(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT max(date) FROM market_data;")
        return cur.fetchone()[0]


def upsert(conn, rows):
    from psycopg2.extras import execute_values

    with conn.cursor() as cur:
        execute_values(cur, UPSERT_SQL, rows, page_size=500)


# ------------------------------------------------------------------------------- main

def parse_args(argv):
    p = argparse.ArgumentParser(description="Ingest NIFTY 50 and India VIX into market_data.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--full", action="store_true", help="reload the last 10 years")
    g.add_argument("--start", type=date.fromisoformat, help="reload from this date (YYYY-MM-DD)")
    p.add_argument("--dry-run", action="store_true", help="download and check, but write nothing")
    return p.parse_args(argv)


def run(args, now_ist=None, downloader=download):
    now_ist = now_ist or datetime.now(IST)
    today = now_ist.date()
    url, last = None, None

    if args.full:
        start = today - timedelta(days=FULL_HISTORY_DAYS)
    elif args.start:
        start = args.start
    else:
        url = load_settings()
        log.info("Database: %s", describe_database_url(url))
        with db_connection(url) as conn:
            last = get_last_date(conn)
        if last is None:
            log.info("market_data is empty; doing a full load.")
            start = today - timedelta(days=FULL_HISTORY_DAYS)
        else:
            start = last - timedelta(days=OVERLAP_DAYS)
            log.info("Last stored date %s; fetching from %s.", last, start)
    if start > today:
        log.info("Start date %s is in the future; nothing to do.", start)
        return 0

    nifty = normalise(downloader(NIFTY_TICKER, start, today), NIFTY_TICKER)
    vix = normalise(downloader(VIX_TICKER, start, today), VIX_TICKER)
    complete = drop_unfinished_session(nifty, now_ist)
    session_open = len(complete) < len(nifty)
    if session_open:
        log.info("Skipping today's bar (%s): the session is not final before 16:00 IST.", today)
    df, report = merge_market_data(complete, drop_unfinished_session(vix, now_ist))

    if report["vix_filled"]:
        log.warning("VIX forward-filled on %d day(s): %s", len(report["vix_filled"]), report["vix_filled"])
    if report["dropped_no_vix"]:
        log.warning("Dropped %d day(s) with no VIX even after filling: %s",
                    len(report["dropped_no_vix"]), report["dropped_no_vix"])
    if report["dropped_no_price"]:
        log.warning("Dropped %d day(s) with missing NIFTY prices: %s",
                    len(report["dropped_no_price"]), report["dropped_no_price"])

    errors, warnings = validate(df)
    for w in warnings:
        log.warning("Data quality: %s", w)
    if errors:
        raise PipelineError(MM_DATA_002, "data-quality gate failed, nothing written: " + "; ".join(errors))

    first, latest = df["date"].iloc[0].date(), df["date"].iloc[-1].date()
    log.info("Fetched %d rows from %s to %s. Rows per year: %s", len(df), first, latest, rows_per_year(df))
    if last is not None and latest <= last:
        reason = ("today's session is not final yet" if session_open
                  else "weekend, market holiday or source not updated yet")
        log.info("No new data: no completed trading day after %s (%s). "
                 "Refreshing the overlap window only.", last, reason)
    if (today - latest).days > 4:
        log.warning("Latest bar %s is %d days old; the source may be stale.", latest, (today - latest).days)

    if args.dry_run:
        log.info("Dry run: %d rows checked, nothing written.", len(df))
        return 0

    url = url or load_settings()
    with db_connection(url) as conn:
        upsert(conn, to_rows(df))
    log.info("Upserted %d rows into market_data.", len(df))
    return 0


def main(argv=None):
    args = parse_args(argv)
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
