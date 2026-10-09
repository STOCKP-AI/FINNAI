"""Integration tests against a real, disposable Postgres (TC-DATA-01 end to end).

Skipped unless TEST_DATABASE_URL is set. CI starts Postgres 17, applies db/migrations/
and sets the variable. Locally, point it at a throwaway database - never at Supabase.
"""

import argparse
import os
from datetime import date, datetime
from urllib.parse import urlparse

import pytest

from marketmood_ml import check_connection
from marketmood_ml.common import MM_DATA_002, PipelineError, db_connection
from marketmood_ml.pipelines import features, ingest
from tests.helpers import FakeYahoo, args, market_frame

TEST_URL = os.getenv("TEST_DATABASE_URL")
EVENING = datetime(2026, 10, 1, 20, 0, tzinfo=ingest.IST)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture
def db(monkeypatch):
    if "supabase" in (urlparse(TEST_URL).hostname or ""):
        pytest.fail("TEST_DATABASE_URL points at Supabase; use a disposable database")
    monkeypatch.setenv("DATABASE_URL", TEST_URL)  # what the pipelines read
    with db_connection(TEST_URL) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE market_data, features")
    return TEST_URL


def snapshot(url, table="market_data"):
    with db_connection(url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*), md5(string_agg(t::text, ',' ORDER BY date)) FROM {table} t")
        return cur.fetchone()


def test_ingest_twice_changes_nothing(db):
    """TC-DATA-01: a second (incremental) run against the real table changes no row."""
    market = market_frame(80, end="2026-10-01")
    yahoo = FakeYahoo(market)
    assert ingest.run(args(start=date(2026, 6, 1)), now_ist=EVENING, downloader=yahoo) == 0
    first = snapshot(db)
    assert first[0] == int((market["date"] >= "2026-06-01").sum())

    assert ingest.run(args(), now_ist=EVENING, downloader=yahoo) == 0
    assert snapshot(db) == first
    assert yahoo.calls[-1][1] == date(2026, 9, 26)  # last stored date - 5 days


def test_upsert_overwrites_corrections_and_fii_flow_defaults_to_zero(db):
    rows = ingest.to_rows(market_frame(3, end="2026-10-01").drop(columns="fii_flow"))
    d, o, h, lo, c, v, vix = rows[-1]
    corrected = (d, o * 1.01, h * 1.01, lo * 1.01, c * 1.01, v, vix)
    with db_connection(db) as conn:
        ingest.upsert(conn, rows)
        ingest.upsert(conn, [corrected])
        assert ingest.get_last_date(conn) == date(2026, 10, 1)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM market_data")
            assert cur.fetchone()[0] == 3
            cur.execute("SELECT close, fii_flow FROM market_data WHERE date = %s", (d,))
            close, fii_flow = cur.fetchone()
    assert close == pytest.approx(c * 1.01)
    assert fii_flow == 0


def test_features_end_to_end_and_idempotent(db):
    market = market_frame(120, end="2026-10-01")
    assert ingest.run(args(start=date(2026, 1, 1)), now_ist=EVENING, downloader=FakeYahoo(market)) == 0

    assert features.run(argparse.Namespace(dry_run=False)) == 0
    first = snapshot(db, "features")
    assert first[0] == 120 - features.WARMUP_ROWS
    with db_connection(db) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(drawdown_60d), count(*) FILTER (WHERE fii_flow <> 0) FROM features")
        max_drawdown, nonzero_fii = cur.fetchone()
    assert max_drawdown <= 0
    assert nonzero_fii == 0

    assert features.run(argparse.Namespace(dry_run=False)) == 0
    assert snapshot(db, "features") == first


def test_dry_runs_write_nothing(db):
    market = market_frame(90, end="2026-10-01")
    assert (
        ingest.run(args(start=date(2026, 1, 1), dry_run=True), now_ist=EVENING, downloader=FakeYahoo(market))
        == 0
    )
    assert snapshot(db)[0] == 0
    with pytest.raises(PipelineError) as ctx:  # empty table: nothing to compute
        features.run(argparse.Namespace(dry_run=True))
    assert ctx.value.code == MM_DATA_002

    assert ingest.run(args(start=date(2026, 1, 1)), now_ist=EVENING, downloader=FakeYahoo(market)) == 0
    assert features.run(argparse.Namespace(dry_run=True)) == 0
    assert snapshot(db, "features")[0] == 0


def test_check_connection_reports_tables(db, caplog):
    caplog.set_level("INFO", logger="check_connection")
    assert check_connection.main() == 0
    assert any("market_data" in r.getMessage() for r in caplog.records)


def test_main_maps_database_errors_to_exit_1(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:wrong@127.0.0.1:1/none")
    assert features.main([]) == 1
    assert ingest.main([]) == 1


def test_floats_are_read_exactly(db):
    """Supabase sets extra_float_digits = 0 (15 digits); db_connection asks for exact values."""
    with db_connection(db) as conn, conn.cursor() as cur:
        cur.execute("SHOW extra_float_digits")
        assert cur.fetchone()[0] == "3"
        cur.execute("SET LOCAL extra_float_digits = 0")
        cur.execute("SELECT 0.0074123776540803181::float8")
        rounded = cur.fetchone()[0]
    with db_connection(db) as conn, conn.cursor() as cur:
        cur.execute("SELECT 0.0074123776540803181::float8")
        exact = cur.fetchone()[0]
    assert exact == 0.0074123776540803181 and rounded != exact
