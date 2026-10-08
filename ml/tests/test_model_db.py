"""Integration tests for model_registry, mm-infer, mm-train and mm-nightly on a real Postgres.

Skipped unless TEST_DATABASE_URL is set (CI applies db/migrations/ to a fresh Postgres 17).
Never point it at Supabase: these tests truncate tables.
"""

import os
from argparse import Namespace
from urllib.parse import urlparse

import psycopg
import pytest

from marketmood_ml import check_connection
from marketmood_ml.common import MM_DATA_003, PipelineError, db_connection
from marketmood_ml.model import artifacts, registry
from marketmood_ml.model.data import COLUMNS, load_frame
from marketmood_ml.model.trainer import train_config
from marketmood_ml.pipelines import features, infer, ingest, nightly, register, train
from tests.model_helpers import FAST, regime_market

TEST_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set"),
]


def seed_market(conn, market):
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market_data (date, open, high, low, close, volume, vix_close) "
            "VALUES (%s, %s, %s, %s, %s, 0, %s)",
            [
                (r.date.date(), r.close, r.close, r.close, r.close, r.vix_close)
                for r in market.itertuples(index=False)
            ],
        )


@pytest.fixture
def db(monkeypatch):
    if "supabase" in (urlparse(TEST_URL).hostname or ""):
        pytest.fail("TEST_DATABASE_URL points at Supabase; use a disposable database")
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    with db_connection(TEST_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE regime_output, model_registry, pipeline_runs, market_data, features")
            cur.execute("ALTER SEQUENCE pipeline_runs_id_seq RESTART")
        seed_market(conn, regime_market())
    assert features.run(Namespace(dry_run=False)) == 0
    return TEST_URL


@pytest.fixture
def released(db, tmp_path):
    """A small model trained on the database's features, saved to tmp and registered."""
    with db_connection(db) as conn:
        frame = load_frame(conn)
        model, out, _ = train_config(frame, FAST, version="hmm-test-a")
        folder = tmp_path / model.version
        sums = artifacts.save_model(model, folder)
        registry.register(conn, model, sums, folder.as_posix(), "experimental")
    return model, folder, sums, out


def count(url, sql):
    with db_connection(url) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def snapshot(url):
    return count(url, "SELECT md5(string_agg(t::text, ',' ORDER BY date)) FROM regime_output t")


def runs(url, job):
    with db_connection(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT status, rows, error FROM pipeline_runs WHERE job = %s ORDER BY id", (job,))
        return cur.fetchall()


def test_infer_writes_every_day_and_twice_changes_nothing(released):
    model, _, _, out = released
    assert infer.main([]) == 0
    n = count(TEST_URL, "SELECT count(*) FROM regime_output")
    assert n == count(TEST_URL, "SELECT count(*) FROM features") == len(out)
    first = snapshot(TEST_URL)
    with db_connection(TEST_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT confirmed_label, signals FROM regime_output ORDER BY date DESC LIMIT 1")
        label, signals = cur.fetchone()
    assert label == out["confirmed_label"].iloc[-1]
    assert signals == out["signals"].iloc[-1]

    assert infer.main([]) == 0
    assert snapshot(TEST_URL) == first
    (s1, r1, _), (s2, r2, _) = runs(TEST_URL, "infer")
    assert (s1, s2) == ("success", "success")
    assert r1["changed"] == n and r2["changed"] == 0 and r2["model_version"] == model.version


def test_infer_dry_run_writes_nothing(released):
    assert infer.main(["--dry-run"]) == 0
    assert count(TEST_URL, "SELECT count(*) FROM regime_output") == 0
    assert runs(TEST_URL, "infer") == []


def test_infer_removes_rows_outside_the_feature_history(released):
    model, _, _, _ = released
    with db_connection(TEST_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO regime_output (date, label, confidence, p_bull, p_sideways, p_crisis, "
            "confirmed_label, model_version) VALUES ('2000-01-03', 'Bull', 1, 1, 0, 0, 'Bull', %s)",
            (model.version,),
        )
    assert infer.main([]) == 0
    assert count(TEST_URL, "SELECT count(*) FROM regime_output WHERE date = '2000-01-03'") == 0
    assert runs(TEST_URL, "infer")[0][1]["deleted"] == 1


def test_infer_refuses_a_tampered_model(released, caplog):
    """TC-ML-08 end to end: a changed file stops the run; nothing is written; the run is logged."""
    _, folder, _, _ = released
    (folder / "surrogate.txt").write_text((folder / "surrogate.txt").read_text() + "# edited\n")
    caplog.set_level("ERROR", logger="infer")
    assert infer.main([]) == 1
    assert "MM-MODEL-001" in caplog.text
    assert count(TEST_URL, "SELECT count(*) FROM regime_output") == 0
    status, _, error = runs(TEST_URL, "infer")[0]
    assert status == "failed" and "MM-MODEL-001" in error


def test_infer_without_an_active_model(db, caplog):
    caplog.set_level("ERROR", logger="infer")
    assert infer.main([]) == 1
    assert "MM-MODEL-003" in caplog.text


def test_registry_keeps_one_active_model_and_immutable_versions(released, tmp_path):
    model, folder, sums, _ = released
    with db_connection(TEST_URL) as conn:
        model.version = "hmm-test-b"
        registry.register(conn, model, sums, folder.as_posix(), "validated")
        active = registry.get_active(conn)
    assert active["version"] == "hmm-test-b" and active["status"] == "validated"
    assert count(TEST_URL, "SELECT count(*) FROM model_registry WHERE is_active") == 1

    with pytest.raises(PipelineError, match="different files"), db_connection(TEST_URL) as conn:
        registry.register(conn, model, {**sums, "model.json": "0" * 64}, folder.as_posix(), "validated")
    assert count(TEST_URL, "SELECT version FROM model_registry WHERE is_active") == "hmm-test-b"

    with pytest.raises(psycopg.errors.UniqueViolation), db_connection(TEST_URL) as conn, conn.cursor() as cur:
        cur.execute("UPDATE model_registry SET is_active = true")
    with pytest.raises(ValueError):
        registry.registry_params(model, sums, "x", "approved", True)


def test_regime_output_constraints(released):
    model, _, _, _ = released
    with pytest.raises(psycopg.errors.CheckViolation), db_connection(TEST_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO regime_output (date, label, confidence, p_bull, p_sideways, p_crisis, "
            "confirmed_label, model_version) VALUES ('2030-01-01', 'Bear', 1, 1, 0, 0, 'Bull', %s)",
            (model.version,),
        )
    with (
        pytest.raises(psycopg.errors.ForeignKeyViolation),
        db_connection(TEST_URL) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "INSERT INTO regime_output (date, label, confidence, p_bull, p_sideways, p_crisis, "
            "confirmed_label, model_version) VALUES ('2030-01-01', 'Bull', 1, 1, 0, 0, 'Bull', 'unknown')"
        )


def test_train_cli_saves_reports_and_registers(db, tmp_path, caplog):
    csv = tmp_path / "input.csv"
    with db_connection(db) as conn:
        load_frame(conn)[COLUMNS].to_csv(csv, index=False)
    out, docs = tmp_path / "models", tmp_path / "docs"
    common = ["--config", "C2", "--out", str(out), "--docs", str(docs)]

    caplog.set_level("ERROR", logger="train")
    assert train.main(["--csv", str(csv), "--register", *common]) == 1  # synthetic data misses gates
    assert "MM-MODEL-002" in caplog.text
    assert count(db, "SELECT count(*) FROM model_registry") == 0

    assert train.main(["--csv", str(csv), "--register", "--allow-experimental", *common]) == 0
    version = count(db, "SELECT version FROM model_registry WHERE is_active")
    assert (out / version / "model.json").is_file()
    assert (docs / "validation.md").read_text().startswith("# Model validation")
    assert (docs / "validation_chart.svg").read_text().startswith("<svg")
    assert infer.main([]) == 0  # absolute artifact_path outside the repository works too

    # From the database: CSV round trips can differ in the last bit, so the same version name
    # would hold different files - refused (MM-MODEL-004); a new name works.
    assert train.main(["--config", "C2", "--out", str(out), "--no-report", "--no-walk-forward"]) in (0, 1)
    assert train.main(["--config", "C2", "--out", str(out), "--no-report", "--version", "hmm-db"]) == 0
    assert (out / "hmm-db" / "model.json").is_file()


def test_register_cli_registers_a_saved_folder(released, tmp_path, caplog):
    model, folder, sums, _ = released
    model.version = "hmm-test-c"
    other = tmp_path / "hmm-test-c"
    artifacts.save_model(model, other)
    assert register.main([str(other)]) == 0
    with db_connection(TEST_URL) as conn:
        active = registry.get_active(conn)
    assert active["version"] == "hmm-test-c" and active["status"] == "experimental"
    assert register.main([str(other), "--status", "retired", "--no-activate"]) == 0
    assert count(TEST_URL, "SELECT status FROM model_registry WHERE version = 'hmm-test-c'") == "retired"
    caplog.set_level("ERROR", logger="register")
    assert register.main([str(tmp_path / "missing")]) == 1


def test_nightly_runs_all_steps_and_logs_one_row(released, monkeypatch):
    monkeypatch.setattr(ingest, "run", lambda args: 0)  # no Yahoo in tests; ingest has its own tests
    assert nightly.main([]) == 0
    ((status, rows, _),) = runs(TEST_URL, "nightly")
    assert status == "success" and rows["ingest"] == "ok" and rows["infer"]["rows"] > 0
    assert runs(TEST_URL, "infer") == []  # the nightly job writes one row, not one per step
    assert nightly.main(["--dry-run"]) == 0
    assert len(runs(TEST_URL, "nightly")) == 1


def test_nightly_failure_is_logged(released, monkeypatch):
    def fail(args):
        raise PipelineError(MM_DATA_003, "Yahoo down")

    monkeypatch.setattr(ingest, "run", fail)
    assert nightly.main([]) == 1
    ((status, rows, error),) = runs(TEST_URL, "nightly")
    assert status == "failed" and rows == {"completed": {}} and "MM-DATA-003" in error


def test_check_connection_shows_the_active_model(released, caplog):
    caplog.set_level("INFO", logger="check_connection")
    assert check_connection.main() == 0
    assert "hmm-test-a (experimental)" in caplog.text


def test_record_run_never_raises(caplog):
    caplog.set_level("WARNING", logger="registry")
    registry.record_run("postgresql://nobody:wrong@127.0.0.1:1/none", "infer", None, "success")
    assert "Could not record" in caplog.text
