"""Unit tests for marketmood_ml.pipelines.ingest (TC-DATA-01, 02, 03, 06, 07).

Run from the repository root:  uv run pytest
No network and no database: Yahoo Finance and Postgres are replaced by fakes.
"""

import unittest
from contextlib import contextmanager
from datetime import date, datetime
from unittest import mock

import numpy as np
import pandas as pd

from marketmood_ml.common import MM_DATA_002, MM_DATA_003, PipelineError, describe_database_url
from marketmood_ml.pipelines import ingest
from tests.helpers import FakeYahoo, args, market_frame, yfinance_frame

FAKE_URL = "postgresql://postgres.abc:s3cret-pw@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


class FakeDatabase:
    """In-memory stand-in for market_data with upsert-on-date semantics."""

    def __init__(self, rows=None):
        self.table = {r[0]: r for r in (rows or [])}
        self.upserts = 0

    def patches(self):
        @contextmanager
        def connection(_url):
            yield self

        def last_date(_conn):
            return max(self.table) if self.table else None

        def upsert(_conn, rows):
            self.upserts += 1
            for r in rows:
                self.table[r[0]] = r

        return [
            mock.patch.object(ingest, "load_settings", return_value=FAKE_URL),
            mock.patch.object(ingest, "db_connection", connection),
            mock.patch.object(ingest, "get_last_date", last_date),
            mock.patch.object(ingest, "upsert", upsert),
        ]


def run_with(db, fake, a, now):
    patches = db.patches()
    for p in patches:
        p.start()
    try:
        return ingest.run(a, now_ist=now, downloader=fake)
    finally:
        for p in patches:
            p.stop()


EVENING = datetime(2026, 10, 1, 20, 0, tzinfo=ingest.IST)


class TestParseYahooResponse(unittest.TestCase):
    """TC-DATA-02: parse a yfinance 1.3.0-shaped response with multi-level columns."""

    def test_picks_close_not_adj_close(self):
        m = market_frame(10)
        out = ingest.normalise(yfinance_frame(m, "^NSEI"), "^NSEI")
        self.assertEqual(list(out.columns), ["date", "open", "high", "low", "close", "volume"])
        np.testing.assert_allclose(out["close"].to_numpy(), m["close"].to_numpy())
        self.assertEqual(out["date"].dt.date.tolist(), m["date"].dt.date.tolist())

    def test_flat_columns_also_work(self):
        m = market_frame(5)
        raw = yfinance_frame(m, "^NSEI")
        raw.columns = raw.columns.get_level_values(0)
        out = ingest.normalise(raw, "^NSEI")
        np.testing.assert_allclose(out["close"].to_numpy(), m["close"].to_numpy())

    def test_missing_column_is_a_fetch_error(self):
        raw = yfinance_frame(market_frame(5), "^NSEI").drop(columns="Volume", level=0)
        with self.assertRaises(PipelineError) as ctx:
            ingest.normalise(raw, "^NSEI")
        self.assertEqual(ctx.exception.code, MM_DATA_003)

    def test_download_sets_auto_adjust_false_and_inclusive_end(self):
        raw = yfinance_frame(market_frame(5), "^NSEI")
        with mock.patch.object(ingest.yf, "download", return_value=raw) as dl:
            ingest.download("^NSEI", date(2026, 9, 1), date(2026, 9, 30), sleep=lambda s: None)
        kwargs = dl.call_args.kwargs
        self.assertIs(kwargs["auto_adjust"], False)
        self.assertEqual(kwargs["end"], "2026-10-01")  # yfinance's end is exclusive


class TestRetries(unittest.TestCase):
    """TC-DATA-06: source timeout -> 3 retries with backoff, then MM-DATA-003."""

    def test_timeout_retries_three_times_then_fails(self):
        sleeps = []
        with (
            mock.patch.object(ingest.yf, "download", side_effect=TimeoutError("read timed out")) as dl,
            self.assertRaises(PipelineError) as ctx,
        ):
            ingest.download("^NSEI", date(2026, 9, 1), date(2026, 9, 30), sleep=sleeps.append)
        self.assertEqual(ctx.exception.code, MM_DATA_003)
        self.assertEqual(dl.call_count, 4)
        self.assertEqual(sleeps, [2, 4, 8])

    def test_empty_frame_is_retried_then_succeeds(self):
        good = yfinance_frame(market_frame(5), "^NSEI")
        with mock.patch.object(ingest.yf, "download", side_effect=[pd.DataFrame(), good]) as dl:
            out = ingest.download("^NSEI", date(2026, 9, 1), date(2026, 9, 30), sleep=lambda s: None)
        self.assertEqual(dl.call_count, 2)
        self.assertFalse(out.empty)

    def test_main_returns_1_on_fetch_failure(self):
        with (
            mock.patch.object(ingest, "run", side_effect=PipelineError(MM_DATA_003, "down")),
            self.assertLogs("ingest", "ERROR") as logs,
        ):
            self.assertEqual(ingest.main(["--full", "--dry-run"]), 1)
        self.assertIn("MM-DATA-003", logs.output[0])


class TestMergeAndVixGaps(unittest.TestCase):
    """Audit A7: VIX gaps are forward-filled (max 2 days) and logged, not silently dropped."""

    def setUp(self):
        self.m = market_frame(10)
        self.nifty = ingest.normalise(yfinance_frame(self.m, "^NSEI"), "^NSEI")

    def vix_without(self, positions):
        v = self.m.drop(index=positions)
        return ingest.normalise(yfinance_frame(v, "^INDIAVIX", "vix_close"), "^INDIAVIX")

    def test_one_missing_vix_day_is_filled(self):
        df, report = ingest.merge_market_data(self.nifty, self.vix_without([4]))
        self.assertEqual(len(df), 10)
        self.assertEqual(report["vix_filled"], [self.m["date"][4].date()])
        self.assertAlmostEqual(df["vix_close"][4], self.m["vix_close"][3])

    def test_three_missing_days_fill_two_and_drop_one(self):
        df, report = ingest.merge_market_data(self.nifty, self.vix_without([4, 5, 6]))
        self.assertEqual(len(report["vix_filled"]), 2)
        self.assertEqual(report["dropped_no_vix"], [self.m["date"][6].date()])
        self.assertEqual(len(df), 9)

    def test_vix_only_days_are_ignored(self):
        nifty = self.nifty.drop(index=[3]).reset_index(drop=True)
        vix = self.vix_without([])
        df, _ = ingest.merge_market_data(nifty, vix)
        self.assertNotIn(self.m["date"][3], set(df["date"]))
        self.assertEqual(len(df), 9)


class TestQualityGate(unittest.TestCase):
    """TC-DATA-07 (and D10 checks): bad rows block the write with MM-DATA-002."""

    def frame(self):
        df = market_frame(30)
        return df.drop(columns="fii_flow")

    def test_clean_frame_passes(self):
        errors, _ = ingest.validate(self.frame())
        self.assertEqual(errors, [])

    def test_close_zero_is_an_error(self):
        df = self.frame()
        df.loc[10, "close"] = 0.0
        errors, _ = ingest.validate(df)
        self.assertTrue(any("price <= 0" in e for e in errors))

    def test_vix_out_of_range_is_an_error(self):
        df = self.frame()
        df.loc[5, "vix_close"] = 150.0
        errors, _ = ingest.validate(df)
        self.assertTrue(any("VIX outside" in e for e in errors))

    def test_big_move_is_a_warning_not_an_error(self):
        df = self.frame()
        df.loc[15:, ["open", "high", "low", "close"]] *= 0.8
        errors, warnings = ingest.validate(df)
        self.assertEqual(errors, [])
        self.assertTrue(any("daily move" in w for w in warnings))

    def test_run_writes_nothing_when_gate_fails(self):
        m = market_frame(20, end="2026-10-01")
        m.loc[18, "close"] = 0.0
        db = FakeDatabase()
        with self.assertRaises(PipelineError) as ctx:
            run_with(db, FakeYahoo(m), args(start=date(2026, 9, 1)), EVENING)
        self.assertEqual(ctx.exception.code, MM_DATA_002)
        self.assertEqual(db.upserts, 0)


class TestIncrementalAndIdempotent(unittest.TestCase):
    """TC-DATA-01 (unit level): running twice changes nothing. TC-DATA-03: market holiday."""

    def test_upsert_sql_is_keyed_on_date_and_updates_every_column(self):
        sql = " ".join(ingest.UPSERT_SQL.split())
        self.assertIn("ON CONFLICT (date) DO UPDATE SET", sql)
        updated = sql.split("DO UPDATE SET", 1)[1]
        for col in ["open", "high", "low", "close", "volume", "vix_close"]:
            self.assertIn(f"{col} = EXCLUDED.{col}", updated)
        self.assertNotIn("fii_flow", sql)

    def test_second_run_changes_nothing(self):
        m = market_frame(40, end="2026-10-01")
        db = FakeDatabase()
        yahoo = FakeYahoo(m)
        self.assertEqual(run_with(db, yahoo, args(start=date(2026, 8, 1)), EVENING), 0)
        first = dict(db.table)
        self.assertEqual(run_with(db, yahoo, args(), EVENING), 0)
        self.assertEqual(db.table, first)
        # the incremental run asked only for the last 5 days onwards
        self.assertEqual(yahoo.calls[-1][1], date(2026, 9, 26))

    def test_market_holiday_logs_no_new_data_and_exits_0(self):
        # 2 Oct 2026 (Gandhi Jayanti) is an NSE holiday; last stored day is 1 Oct.
        m = market_frame(40, end="2026-10-01")
        db = FakeDatabase(ingest.to_rows(m.drop(columns="fii_flow")))
        holiday_evening = datetime(2026, 10, 2, 20, 0, tzinfo=ingest.IST)
        with self.assertLogs("ingest", "INFO") as logs:
            code = run_with(db, FakeYahoo(m), args(), holiday_evening)
        self.assertEqual(code, 0)
        self.assertTrue(any("No new data" in line for line in logs.output))
        self.assertEqual(max(db.table), date(2026, 10, 1))

    def test_dry_run_writes_nothing(self):
        m = market_frame(40, end="2026-10-01")
        db = FakeDatabase()
        self.assertEqual(run_with(db, FakeYahoo(m), args(full=True, dry_run=True), EVENING), 0)
        self.assertEqual(db.upserts, 0)


class TestLatestDay(unittest.TestCase):
    """Review fixes: never invent today's VIX; clear message before 16:00 IST."""

    def test_vix_lagging_on_latest_day_is_not_filled(self):
        m = market_frame(40, end="2026-10-01")
        db = FakeDatabase()
        yahoo = FakeYahoo(m, vix_missing=["2026-10-01"])
        with self.assertLogs("ingest", "INFO") as logs:
            run_with(db, yahoo, args(start=date(2026, 8, 1)), EVENING)
        self.assertEqual(max(db.table), date(2026, 9, 30))
        self.assertTrue(any("no VIX" in line and "2026, 10, 1" in line for line in logs.output))

    def test_run_before_16_ist_skips_today_with_clear_reason(self):
        m = market_frame(40, end="2026-10-01")
        db = FakeDatabase(ingest.to_rows(m.iloc[:-1].drop(columns="fii_flow")))
        afternoon = datetime(2026, 10, 1, 15, 0, tzinfo=ingest.IST)
        with self.assertLogs("ingest", "INFO") as logs:
            self.assertEqual(run_with(db, FakeYahoo(m), args(), afternoon), 0)
        text = "\n".join(logs.output)
        self.assertIn("not final", text)
        self.assertNotIn("weekend", text)
        self.assertNotIn("forward-filled", text)
        self.assertEqual(max(db.table), date(2026, 9, 30))

    def test_database_error_exits_1_with_code(self):
        import psycopg

        with (
            mock.patch.object(ingest, "run", side_effect=psycopg.OperationalError("timeout expired")),
            self.assertLogs("ingest", "ERROR") as logs,
        ):
            self.assertEqual(ingest.main([]), 1)
        self.assertIn("MM-DB-001", logs.output[0])


class TestUnfinishedSession(unittest.TestCase):
    def test_todays_bar_dropped_before_16_ist(self):
        m = market_frame(5, end="2026-10-01").drop(columns="fii_flow")
        noon = datetime(2026, 10, 1, 12, 0, tzinfo=ingest.IST)
        self.assertEqual(len(ingest.drop_unfinished_session(m, noon)), 4)
        self.assertEqual(len(ingest.drop_unfinished_session(m, EVENING)), 5)


class TestConnectionDescription(unittest.TestCase):
    def test_never_prints_password_and_detects_pooler(self):
        text = describe_database_url(FAKE_URL)
        self.assertNotIn("s3cret-pw", text)
        self.assertIn("pooler (session mode)", text)

    def test_detects_direct_connection(self):
        text = describe_database_url("postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres")
        self.assertIn("direct connection", text)


if __name__ == "__main__":
    unittest.main()
