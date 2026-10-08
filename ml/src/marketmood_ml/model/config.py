"""Model settings, the pre-registered configurations, reference periods and gates.

Everything that decides which model is released lives here, so it can be reviewed in
one place. The configurations and the selection rule were written down before the
final sweep was run (docs/adr/0001-regime-model.md); do not add a configuration
after looking at results without logging it as a new run.
"""

from dataclasses import asdict, dataclass

from marketmood_ml.common import FEATURE_COLUMNS

LABELS = ("Bull", "Sideways", "Crisis")  # index order used for probabilities and the surrogate

# Right-skewed positive features (skew 4-6.6 on the training data) are log-transformed so
# the Gaussian emissions fit; vix_change_30d is a percentage change, so log1p.
LOG_FEATURES = ("volatility_20d", "vix_level", "bb_width")
LOG1P_FEATURES = ("vix_change_30d",)

TEST_MONTHS = 24  # train on everything up to 24 months before the last date
LABEL_RETURN_DAYS = 20  # trailing return used to name the states
CONFIRM_DAYS = 2  # a regime change is confirmed after this many consecutive days
WALK_FORWARD_START = 2019  # first year labelled by a model refitted on earlier years only


@dataclass(frozen=True)
class ModelConfig:
    name: str
    description: str
    features: tuple[str, ...] = tuple(FEATURE_COLUMNS)
    log_transform: bool = True
    n_states: int = 3
    covariance_type: str = "full"
    seeds: tuple[int, ...] = tuple(range(10))
    n_iter: int = 500
    tol: float = 1e-4

    def to_dict(self):
        d = asdict(self)
        d["features"] = list(self.features)
        d["seeds"] = list(self.seeds)
        return d


_ALL = tuple(FEATURE_COLUMNS)
_NO_BB = tuple(f for f in _ALL if f != "bb_width")
_NO_BB_VIXCHG = tuple(f for f in _NO_BB if f != "vix_change_30d")

# Pre-registered, in priority order (8 Oct 2026). Selection rule: the first that passes
# every gate; if none does, the most reference periods correct, then the highest macro-F1.
CONFIGS = (
    ModelConfig("C1", "log-transform, 8 features, full covariance (primary)"),
    ModelConfig("C2", "log-transform, 8 features, diagonal covariance", covariance_type="diag"),
    ModelConfig("C3", "log-transform, 7 features (no bb_width), full covariance", features=_NO_BB),
    ModelConfig(
        "C4", "log-transform, 6 features (no bb_width, vix_change_30d), full", features=_NO_BB_VIXCHG
    ),
    ModelConfig("C5", "log-transform, 8 features, full covariance, 4 states", n_states=4),
    ModelConfig("C6", "no transform, 8 features, full covariance", log_transform=False),
    ModelConfig(
        "C7",
        "log-transform, 4 core features, full covariance",
        features=("volatility_20d", "vix_level", "sharpe_60d", "drawdown_60d"),
    ),
)


def get_config(name):
    for c in CONFIGS:
        if c.name == name:
            return c
    raise KeyError(f"unknown configuration {name!r}; choose from {[c.name for c in CONFIGS]}")


@dataclass(frozen=True)
class ReferencePeriod:
    start: str
    end: str
    expected: tuple[str, ...]
    event: str


# Full Project Document 12.5: six periods inside the data window.
REFERENCE_PERIODS = (
    ReferencePeriod("2017-01-01", "2018-01-31", ("Bull",), "Steady low-volatility rally"),
    ReferencePeriod("2018-09-01", "2018-10-31", ("Crisis", "Sideways"), "IL&FS credit scare"),
    ReferencePeriod("2020-03-01", "2020-04-30", ("Crisis",), "COVID crash"),
    ReferencePeriod("2020-06-01", "2021-10-31", ("Bull",), "Post-COVID bull run"),
    ReferencePeriod("2022-01-01", "2022-06-30", ("Crisis", "Sideways"), "Rate hikes, Russia-Ukraine"),
    ReferencePeriod("2023-04-01", "2023-12-31", ("Bull",), "Broad rally to new highs"),
)

# Gate G2 (Prototype Build Plan v2.1 section 7, Full Project Document 12.6).
GATES = {
    "periods_correct_min": 5,  # of 6
    "macro_f1_min": 0.60,  # confirmed labels vs objective reference labels
    "fidelity_min": 0.95,  # surrogate agreement with the HMM label
    "switches_per_year_max": 12,  # confirmed switches per year on the test period (strictly fewer)
    "transition_lag_max": 7,  # trading days, March 2020 crash
}

# The surrogate is kept small so its text file can be reviewed and committed (about 45 KB).
# Measured on the released model: same fidelity as the plan's 200-tree version (99%) and
# the same out-of-sample agreement, at 1/20 of the size.
SURROGATE_PARAMS = {
    "objective": "multiclass",
    "num_class": len(LABELS),
    "num_leaves": 15,
    "max_depth": 4,
    "learning_rate": 0.5,
    "min_data_in_leaf": 20,
    "seed": 0,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
    "verbose": -1,
}
SURROGATE_ROUNDS = 10
TOP_SIGNALS = 3
