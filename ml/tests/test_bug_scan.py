"""Regression tests for the bug scan of 15 Oct 2026 (pipeline and model)."""

import numpy as np
import pandas as pd
import pytest

from marketmood_ml import common
from marketmood_ml.model import artifacts, hmm
from marketmood_ml.pipelines import ingest
from tests.model_helpers import FAST


def test_nan_log_likelihood_never_wins(monkeypatch):
    from hmmlearn.hmm import GaussianHMM

    calls = []
    real_score = GaussianHMM.score

    def score(self, x):
        calls.append(self.random_state)
        return float("nan") if self.random_state == FAST.seeds[0] else real_score(self, x)

    monkeypatch.setattr(GaussianHMM, "score", score)
    rng = np.random.default_rng(0)
    x = np.vstack([rng.normal(0, 1, (150, 2)), rng.normal(4, 1, (150, 2))])
    _, seed, ll, logliks = hmm.fit_best_hmm(x, FAST)
    assert np.isnan(logliks[FAST.seeds[0]]) and seed != FAST.seeds[0] and np.isfinite(ll)


def test_all_seeds_degenerate_is_an_error(monkeypatch):
    from hmmlearn.hmm import GaussianHMM

    monkeypatch.setattr(GaussianHMM, "score", lambda self, x: float("nan"))
    with pytest.raises(ValueError, match="non-finite"):
        hmm.fit_best_hmm(np.random.default_rng(1).normal(size=(200, 2)), FAST)


def test_duplicate_dates_keep_the_newest_row():
    idx = pd.to_datetime(["2026-10-08"] * 20 + ["2026-10-07"])
    raw = pd.DataFrame(
        {"Open": range(21), "High": range(21), "Low": range(21), "Close": range(21), "Volume": range(21)},
        index=idx,
    )
    out = ingest.normalise(raw, "^NSEI")
    assert list(out["date"].dt.strftime("%Y-%m-%d")) == ["2026-10-07", "2026-10-08"]
    assert out.loc[out["date"] == "2026-10-08", "close"].item() == 19  # the last row of that date


def test_connection_is_closed_when_setup_fails(monkeypatch):
    import psycopg

    class Conn:
        closed = False

        def execute(self, sql):
            raise psycopg.OperationalError("SET failed")

        def close(self):
            self.closed = True

    conn = Conn()
    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: conn)
    with pytest.raises(psycopg.OperationalError), common.db_connection("postgresql://x"):
        pass
    assert conn.closed


def test_unreadable_metrics_json_is_ignored(tmp_path):
    (tmp_path / "metrics.json").write_text("{not json", encoding="utf-8")
    assert artifacts.read_metrics(tmp_path) == {}
    (tmp_path / "metrics.json").write_text("[1, 2]", encoding="utf-8")
    assert artifacts.read_metrics(tmp_path) == {}
    assert artifacts.read_metrics(tmp_path / "missing") == {}
