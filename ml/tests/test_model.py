"""Unit tests for the regime model (TC-ML-01..04, 07..09, 11). No network, no database."""

import itertools
import json

import numpy as np
import pandas as pd
import pytest

from marketmood_ml.common import MM_MODEL_001, PipelineError
from marketmood_ml.model import artifacts, backtest, evaluation, explain, labeling, trainer
from marketmood_ml.model.config import CONFIGS, LABELS, ModelConfig, get_config
from marketmood_ml.model.hmm import HmmParams, Scaler, filtered_probs, fit_best_hmm, transform
from marketmood_ml.model.predict import predict_history, validate_output
from tests.model_helpers import FAST, regime_frame


@pytest.fixture(scope="module")
def frame():
    return regime_frame()


@pytest.fixture(scope="module")
def trained(frame):
    return trainer.train_config(frame, FAST, version="hmm-test")


def simple_params():
    return HmmParams(
        startprob=np.array([0.6, 0.4]),
        transmat=np.array([[0.9, 0.1], [0.2, 0.8]]),
        means=np.array([[0.0], [3.0]]),
        covars=np.array([[[1.0]], [[1.0]]]),
    )


# --- TC-ML-01: known regimes are recovered ------------------------------------------------


def test_recovers_known_regimes_from_synthetic_data():
    """TC-ML-01: >= 90% of days recovered after aligning state numbers with the truth."""
    rng = np.random.default_rng(0)
    truth, state = [], 0
    for _ in range(1500):
        if rng.random() > 0.97:
            state = int(rng.choice([s for s in range(3) if s != state]))
        truth.append(state)
    truth = np.array(truth)
    centres = np.array([[0, 0, 0], [3, 0, -2], [-2, 3, 2]], dtype=float)
    x = centres[truth] + rng.normal(0, 0.7, (len(truth), 3))
    config = ModelConfig("R", "recovery", features=("a", "b", "c"), covariance_type="diag", seeds=(0, 1, 2))
    params, _, _, _ = fit_best_hmm(x, config)
    found = filtered_probs(params, x).argmax(axis=1)
    best = max(np.mean(np.array(p)[found] == truth) for p in itertools.permutations(range(3)))
    assert best >= 0.90


# --- TC-ML-02: no look-ahead -------------------------------------------------------------


def test_filtered_probabilities_use_no_future_data(trained, frame):
    """TC-ML-02: P(state_t) from days 0..t equals P(state_t) computed with the full history."""
    model, _, _ = trained
    x = model.scaler.apply(transform(frame, model.features, model.log_transform))
    full = filtered_probs(model.hmm, x)
    for t in (0, 1, 50, 300, len(x) - 1):
        np.testing.assert_allclose(filtered_probs(model.hmm, x[: t + 1])[-1], full[t], rtol=0, atol=1e-12)


def test_filtered_probabilities_are_distributions():
    x = np.array([[0.1], [2.9], [3.2], [-0.5]])
    p = filtered_probs(simple_params(), x)
    np.testing.assert_allclose(p.sum(axis=1), 1.0)
    assert p[0, 0] > 0.5 and p[2, 1] > 0.9 and p[3, 0] > 0.5


def test_published_history_has_no_look_ahead(trained, frame):
    """Adding a future day never changes earlier published labels or probabilities."""
    model, _, _ = trained
    full = predict_history(model, frame)
    head = predict_history(model, frame.iloc[:400])
    pd.testing.assert_frame_equal(full.iloc[:400].reset_index(drop=True), head)


# --- TC-ML-03: reproducible training -----------------------------------------------------


def test_training_twice_with_the_same_seed_is_identical(frame, trained):
    """TC-ML-03: identical parameters, labels and surrogate."""
    model, out, _ = trained
    again, out2, _ = trainer.train_config(frame, FAST, version="hmm-test")
    assert again.to_json() == model.to_json()
    assert again.surrogate_text == model.surrogate_text
    pd.testing.assert_frame_equal(out, out2)


# --- TC-ML-04: automatic labeling ----------------------------------------------------------


def labelled_market(state_of_block, block_rets, block_vols, days=60):
    states, closes, vols, price = [], [], [], 100.0
    for s, r, v in zip(state_of_block, block_rets, block_vols, strict=True):
        for _ in range(days):
            price *= 1 + r
            states.append(s)
            closes.append(price)
            vols.append(v)
    return np.array(states), np.array(closes), np.array(vols)


@pytest.mark.parametrize("perm", list(itertools.permutations(range(3))))
def test_label_map_follows_the_market_not_the_state_number(perm):
    """TC-ML-04: Bull = highest return; Crisis = high-volatility state with negative return."""
    bull, side, crisis = perm
    blocks = [bull, side, crisis, bull, side, crisis]
    rets = [0.004, 0.0005, -0.006] * 2
    vols = [0.006, 0.01, 0.03] * 2
    states, close, vol = labelled_market(blocks, rets, vols)
    assert labeling.make_label_map(states, close, vol, 3) == {
        bull: "Bull",
        side: "Sideways",
        crisis: "Crisis",
    }


def test_crash_followed_by_rebound_is_still_crisis():
    """The forward-return rule called this Bull; trailing returns keep it Crisis."""
    states, close, vol = labelled_market(
        [0, 2, 1, 0], [0.003, -0.008, 0.02, 0.002], [0.006, 0.03, 0.012, 0.006]
    )
    mapping = labeling.make_label_map(states, close, vol, 3)
    assert mapping[2] == "Crisis"


def test_high_vol_state_with_positive_return_falls_back_to_lowest_return():
    states, close, vol = labelled_market(
        [0, 1, 2, 0], [0.003, 0.001, 0.005, 0.003], [0.006, 0.01, 0.03, 0.006]
    )
    mapping = labeling.make_label_map(states, close, vol, 3)
    assert mapping[1] == "Crisis" and mapping[2] == "Bull" and mapping[0] == "Sideways"


def test_four_states_and_unvisited_states_are_sideways():
    states, close, vol = labelled_market(
        [0, 1, 2, 0], [0.004, 0.0005, -0.006, 0.004], [0.006, 0.01, 0.03, 0.006]
    )
    mapping = labeling.make_label_map(states, close, vol, 4)
    assert mapping == {0: "Bull", 1: "Sideways", 2: "Crisis", 3: "Sideways"}
    probs = np.array([[0.1, 0.2, 0.3, 0.4]])
    np.testing.assert_allclose(labeling.label_probabilities(probs, mapping, LABELS), [[0.1, 0.6, 0.3]])


def test_label_map_needs_two_visited_states():
    with pytest.raises(ValueError):
        labeling.make_label_map(np.zeros(50, dtype=int), np.linspace(1, 2, 50), np.ones(50), 3)


# --- TC-ML-09: 2-day confirmation -----------------------------------------------------------


def test_single_day_flip_does_not_change_the_confirmed_label():
    """TC-ML-09: confirmed label unchanged until the new label holds for 2 days."""
    assert labeling.confirm_labels(["Bull", "Bull", "Crisis", "Bull", "Bull"]) == ["Bull"] * 5
    assert labeling.confirm_labels(["Bull", "Crisis", "Crisis", "Crisis"]) == [
        "Bull",
        "Bull",
        "Crisis",
        "Crisis",
    ]
    assert labeling.confirm_labels(["Sideways"]) == ["Sideways"]
    assert labeling.confirm_labels([]) == []
    assert labeling.confirm_labels(["Bull", "Crisis", "Crisis", "Sideways"], days=3) == ["Bull"] * 4


# --- TC-ML-07: surrogate fidelity and signals -----------------------------------------------


def test_surrogate_fidelity_at_least_95_percent(trained):
    """TC-ML-07."""
    _, _, metrics = trained
    assert metrics["surrogate_fidelity"] >= 0.95
    assert 0 <= metrics["surrogate_fidelity_test"] <= 1


def test_signals_are_the_top_three_contributions(trained, frame):
    model, out, _ = trained
    x = model.scaler.apply(transform(frame, model.features, model.log_transform))
    contrib = explain.contributions(model.surrogate(), x)
    assert contrib.shape == (len(frame), 3, len(model.features))
    t = len(frame) - 1
    signals = out["signals"].iloc[t]
    assert len(signals) == 3
    row = contrib[t, LABELS.index(out["confirmed_label"].iloc[t])]
    assert signals[0]["feature"] == model.features[int(np.argmax(np.abs(row)))]
    assert {s["direction"] for s in signals} <= {"up", "down"}
    assert abs(signals[0]["contribution"]) >= abs(signals[-1]["contribution"])


def test_top_signals_direction_and_rounding():
    s = explain.top_signals(
        np.array([0.1, -2.0, 0.5]), np.array([1.234567891, 5.0, 0.2]), [1.0, 6.0, 0.1], ["a", "b", "c"], k=2
    )
    assert s == [
        {"feature": "b", "value": 5.0, "contribution": -2.0, "direction": "down"},
        {"feature": "c", "value": 0.2, "contribution": 0.5, "direction": "up"},
    ]


# --- training outputs, evaluation and selection ------------------------------------------------


def test_trained_output_is_valid(trained, frame):
    model, out, metrics = trained
    assert validate_output(out) == []
    assert len(out) == len(frame)
    assert set(out["model_version"]) == {"hmm-test"}
    assert model.train["rows"] + model.train["test_rows"] == len(frame)
    assert set(metrics["gates"]) == {"periods", "macro_f1", "fidelity", "stability", "transition_lag"}
    assert metrics["passed"] == all(metrics["gates"].values())
    assert sum(metrics["label_days"].values()) == len(frame)


def test_validate_output_catches_problems(trained):
    _, out, _ = trained
    bad = out.copy()
    bad.loc[0, "p_bull"] = np.nan
    assert "NaN or infinite probabilities" in validate_output(bad)
    bad = out.copy()
    bad.loc[0, ["p_bull", "p_sideways", "p_crisis"]] = [0.5, 0.5, 0.5]
    assert "probabilities do not sum to 1" in validate_output(bad)
    bad = out.copy()
    bad.loc[0, "p_bull"] = 1.5
    assert "probabilities outside 0..1" in validate_output(bad)
    bad = out.copy()
    bad.loc[0, "label"] = "Bear"
    assert "unknown label" in validate_output(bad)
    assert validate_output(pd.concat([out, out.iloc[:1]])) == ["duplicate dates"]
    assert validate_output(out.iloc[:0]) == ["no rows"]


def test_reference_labels_and_scores():
    close = np.r_[np.linspace(100, 130, 60), np.linspace(130, 100, 30), np.full(40, 100.0)]
    vix = np.r_[np.full(60, 12.0), np.full(30, 40.0), np.full(40, 15.0)]
    ref = evaluation.reference_labels(close, vix)
    assert ref[0] is None and ref[-1] is None
    assert ref[30] == "Bull" and ref[85] == "Crisis" and ref[105] == "Sideways"
    assert evaluation.macro_f1(ref, np.where(ref == None, "Bull", ref)) == pytest.approx(1.0)  # noqa: E711

    r = np.array(["Bull", "Bull", "Sideways", "Crisis", None], dtype=object)
    p = np.array(["Bull", "Sideways", "Sideways", "Crisis", "Crisis"], dtype=object)
    assert evaluation.macro_f1(r, p) == pytest.approx((2 / 3 + 2 / 3 + 1) / 3)
    conf = evaluation.confusion(r, p)
    assert conf["Bull"] == {"Bull": 1, "Sideways": 1, "Crisis": 0}
    assert conf["Crisis"]["Crisis"] == 1
    assert evaluation.macro_f1(np.array([None], dtype=object), np.array(["Bull"], dtype=object)) == 0.0


def test_switches_lag_and_periods():
    assert evaluation.switches_per_year(["Bull"] * 252) == 0
    assert evaluation.switches_per_year(["Bull"] * 126 + ["Crisis"] * 126) == 1
    assert evaluation.switches_per_year(["Bull"]) == 0.0
    dates = pd.bdate_range("2020-02-24", periods=10)
    ref = ["Sideways"] * 3 + ["Crisis"] * 7
    assert evaluation.transition_lag(dates, ["Sideways"] * 5 + ["Crisis"] * 5, ref) == 2
    assert evaluation.transition_lag(dates, ["Crisis"] * 10, ref) == 0
    assert evaluation.transition_lag(dates, ["Bull"] * 10, ref) is None
    assert evaluation.transition_lag(dates, ["Bull"] * 10, ["Bull"] * 10) is None
    rows = evaluation.score_periods(pd.bdate_range("2017-01-02", periods=5), ["Bull"] * 5)
    assert rows[0]["correct"] and rows[0]["share"] == 1.0
    assert rows[2]["top"] is None and not rows[2]["correct"]


def test_gates():
    m = {
        "periods_correct": 5,
        "macro_f1": 0.61,
        "surrogate_fidelity": 0.96,
        "switches_per_year_test": 11.9,
        "transition_lag_2020": 7,
    }
    assert all(evaluation.check_gates(m).values())
    m.update(macro_f1=0.55, switches_per_year_test=12, transition_lag_2020=None)
    gates = evaluation.check_gates(m)
    assert not gates["macro_f1"] and not gates["stability"] and not gates["transition_lag"]


def test_benchmark_rule():
    f = pd.DataFrame(
        {"vix_level": [30, 30, 15], "drawdown_60d": [-0.2, -0.05, -0.01], "sharpe_60d": [0.1, -0.1, 0.2]}
    )
    assert list(evaluation.benchmark_labels(f)) == ["Crisis", "Sideways", "Bull"]


def test_selection_rule():
    def result(name, passed, periods, f1):
        return (name, None, None, {"passed": passed, "periods_correct": periods, "macro_f1": f1})

    assert trainer.select([result("A", False, 6, 0.9), result("B", True, 5, 0.6)])[0] == "B"
    assert (
        trainer.select([result("A", False, 4, 0.9), result("B", False, 5, 0.5), result("C", False, 5, 0.55)])[
            0
        ]
        == "C"
    )
    assert trainer.select([result("A", False, 5, 0.5), result("B", False, 5, 0.5)])[0] == "A"


def test_sweep_logs_every_configuration(frame, caplog):
    caplog.set_level("INFO", logger="train")
    results = trainer.run_sweep(
        frame, [FAST, ModelConfig("U", "two states", seeds=(0,), n_iter=50, n_states=2)]
    )
    assert [r[0].name for r in results] == ["T", "U"]
    assert sum("periods" in r.getMessage() for r in caplog.records) == 2


def test_configs_are_pre_registered():
    assert [c.name for c in CONFIGS] == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
    assert len(CONFIGS) <= 8  # Prototype Build Plan: at most 8 pre-registered configurations
    assert all("fii_flow" not in c.features for c in CONFIGS)
    assert get_config("C2").covariance_type == "diag"
    with pytest.raises(KeyError):
        get_config("C9")


def test_split_needs_enough_history(frame):
    with pytest.raises(PipelineError):
        trainer.train_rows(frame["date"].iloc[:300])


# --- transform and scaling --------------------------------------------------------------------


def test_transform_and_scaler():
    f = pd.DataFrame({"volatility_20d": [0.01, 0.02], "vix_change_30d": [0.0, 1.0], "sharpe_60d": [1.0, 1.0]})
    x = transform(f, ["volatility_20d", "vix_change_30d", "sharpe_60d"], True)
    np.testing.assert_allclose(x[:, 0], np.log([0.01, 0.02]))
    np.testing.assert_allclose(x[:, 1], np.log1p([0.0, 1.0]))
    s = Scaler.fit(x)
    assert s.scale[2] == 1.0  # constant column
    np.testing.assert_allclose(s.apply(x).mean(axis=0), 0, atol=1e-12)
    with pytest.raises(PipelineError):
        transform(pd.DataFrame({"vix_level": [0.0]}), ["vix_level"], True)


# --- TC-ML-08: artifacts and checksums ----------------------------------------------------------


def test_save_and_load_round_trip(tmp_path, trained, frame):
    model, out, _ = trained
    sums = artifacts.save_model(model, tmp_path / model.version)
    assert set(sums) == set(artifacts.MODEL_FILES)
    assert artifacts.save_model(model, tmp_path / "again") == sums  # deterministic files
    loaded = artifacts.load_model(tmp_path / model.version, sums)
    pd.testing.assert_frame_equal(predict_history(loaded, frame), out)
    text = (tmp_path / model.version / "model.json").read_bytes()
    assert b"\r\n" not in text and text.endswith(b"\n")
    assert json.loads((tmp_path / model.version / "metrics.json").read_text())["passed"] in (True, False)


def test_modified_artifact_is_refused(tmp_path, trained):
    """TC-ML-08: a changed byte, a missing file or a wrong file list -> MM-MODEL-001."""
    model, _, _ = trained
    folder = tmp_path / model.version
    sums = artifacts.save_model(model, folder)
    path = folder / "model.json"
    original = path.read_bytes()
    path.write_text(path.read_text().replace('"seed": ', '"seed":  '))
    with pytest.raises(PipelineError) as ctx:
        artifacts.load_model(folder, sums)
    assert ctx.value.code == MM_MODEL_001 and "checksum mismatch" in str(ctx.value)

    path.write_bytes(original)  # restore, then remove a file
    (folder / "surrogate.txt").unlink()
    with pytest.raises(PipelineError, match="missing"):
        artifacts.load_model(folder, sums)
    with pytest.raises(PipelineError, match="registry lists"):
        artifacts.load_model(folder, {"model.json": sums["model.json"]})


def test_unknown_model_format_is_refused(trained):
    model, _, _ = trained
    doc = json.loads(model.to_json())
    doc["format"] = 99
    with pytest.raises(PipelineError) as ctx:
        artifacts.TrainedModel.from_files(json.dumps(doc), model.surrogate_text)
    assert ctx.value.code == MM_MODEL_001


def test_artifact_path_is_relative_inside_the_repository(tmp_path):
    assert artifacts.artifact_path(artifacts.MODELS_DIR / "hmm-x") == "ml/models/hmm-x"
    assert artifacts.artifact_path(tmp_path) == tmp_path.resolve().as_posix()
    assert artifacts.resolve_artifact("ml/models/hmm-x") == artifacts.REPO_ROOT / "ml" / "models" / "hmm-x"
    assert artifacts.resolve_artifact(tmp_path.as_posix()) == tmp_path


def test_normalise_text():
    assert artifacts.normalise_text("a  \r\nb\n\n\n") == "a\nb\n"


# --- TC-ML-11: backtest ---------------------------------------------------------------------------


def test_backtest_delay_changes_results_and_reruns_are_identical(frame, trained):
    """TC-ML-11."""
    _, out, _ = trained
    labels = list(out["confirmed_label"])
    m1, d1 = backtest.backtest(frame["close"], labels, delay=1)
    m1b, d1b = backtest.backtest(frame["close"], labels, delay=1)
    m2, _ = backtest.backtest(frame["close"], labels, delay=2)
    assert m1 == m1b
    pd.testing.assert_frame_equal(d1, d1b)
    assert m1["strategy"] != m2["strategy"]
    assert m1["buy_hold"] == m2["buy_hold"]
    with pytest.raises(ValueError):
        backtest.backtest(frame["close"], labels, delay=0)


def test_backtest_arithmetic():
    close = [100, 110, 99, 99]
    metrics, daily = backtest.backtest(close, ["Bull", "Crisis", "Crisis", "Crisis"], cost=0.0, cash_rate=0.0)
    # day 1 return +10% at weight 1.0 (Bull from day 0); from day 2 weight 0.3: -10% * 0.3
    np.testing.assert_allclose(daily["strategy"], [0.0, 0.10, -0.03, 0.0])
    assert metrics["weight_changes"] == 1
    assert metrics["buy_hold"]["final_value"] == pytest.approx(0.99)


def test_confidence_is_the_probability_of_the_label_shown(trained):
    _, out, _ = trained
    col = {"Bull": "p_bull", "Sideways": "p_sideways", "Crisis": "p_crisis"}
    shown = [row[col[row["confirmed_label"]]] for _, row in out.iterrows()]
    np.testing.assert_array_equal(out["confidence"].to_numpy(), np.array(shown))
    assert out["surrogate_agrees"].dtype == bool and out["surrogate_agrees"].mean() > 0.9


def test_released_versions_are_never_overwritten(tmp_path, trained):
    """MM-MODEL-004: same version name with different files is refused; identical files are fine."""
    model, _, _ = trained
    folder = tmp_path / model.version
    sums = artifacts.save_model(model, folder)
    assert artifacts.save_model(model, folder) == sums
    (folder / "surrogate.txt").write_text("changed\n")
    with pytest.raises(PipelineError) as ctx:
        artifacts.save_model(model, folder)
    assert ctx.value.code == "MM-MODEL-004"


def test_walk_forward_refits_on_earlier_years_only(frame):
    wf = trainer.walk_forward(frame, FAST, start_year=2020)
    assert wf["start"].startswith("2020")
    assert sum(wf["label_days"].values()) == int((pd.to_datetime(frame["date"]) >= "2020-01-01").sum())
    assert wf["periods_scored"] == sum(1 for p in wf["periods"])
    assert trainer.walk_forward(frame, FAST, start_year=2030) is None


def test_walk_forward_labels_do_not_change_when_later_years_are_added(frame):
    """Each year's labels come from a model fitted before that year: later data cannot change them."""
    dates = pd.to_datetime(frame["date"])
    short = frame[dates < "2021-01-01"]
    a = trainer.fit_and_label(frame, FAST, int((dates < "2020-01-01").sum()), len(short))
    b = trainer.fit_and_label(short, FAST, int((dates < "2020-01-01").sum()), len(short))
    assert a == b
