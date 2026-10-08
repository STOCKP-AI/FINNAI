"""Gaussian HMM: feature transform, scaling, training over several seeds, causal filtering.

The only function that turns observations into regime probabilities is filtered_probs().
It runs the forward algorithm: the probabilities for day t use days 1..t only. Never use
hmmlearn's predict() / predict_proba() for anything shown to users or used in evaluation:
both look at future days (Viterbi / forward-backward).
"""

import logging
from dataclasses import dataclass

import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from marketmood_ml.common import MM_DATA_002, PipelineError
from marketmood_ml.model.config import LOG1P_FEATURES, LOG_FEATURES

log = logging.getLogger("model")


def transform(frame, features, log_transform):
    """Return the model inputs as a float array (rows = days), before scaling."""
    out = frame[list(features)].astype(float).copy()
    if log_transform:
        with np.errstate(divide="ignore", invalid="ignore"):  # bad values are caught below
            for col in features:
                if col in LOG_FEATURES:
                    out[col] = np.log(out[col])
                elif col in LOG1P_FEATURES:
                    out[col] = np.log1p(out[col])
    values = out.to_numpy()
    if not np.isfinite(values).all():
        raise PipelineError(MM_DATA_002, "model inputs contain NaN or infinite values after the transform")
    return values


@dataclass
class Scaler:
    """Standardisation fitted on the training rows only (population std, like scikit-learn)."""

    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, x):
        scale = x.std(axis=0)
        scale[scale == 0] = 1.0  # a constant column must not divide by zero
        return cls(mean=x.mean(axis=0), scale=scale)

    def apply(self, x):
        return (x - self.mean) / self.scale


@dataclass
class HmmParams:
    """Everything filtered_probs() needs. covars are always full (K, D, D) matrices."""

    startprob: np.ndarray
    transmat: np.ndarray
    means: np.ndarray
    covars: np.ndarray

    @classmethod
    def from_hmmlearn(cls, model):
        # hmmlearn's covars_ property returns full matrices for every covariance type.
        return cls(
            startprob=np.asarray(model.startprob_, dtype=float),
            transmat=np.asarray(model.transmat_, dtype=float),
            means=np.asarray(model.means_, dtype=float),
            covars=np.asarray(model.covars_, dtype=float),
        )

    @property
    def n_states(self):
        return len(self.startprob)


def fit_best_hmm(x_train, config):
    """Fit one GaussianHMM per seed; return (params, best_seed, best_loglik, all logliks).

    EM finds local optima, so several seeds are tried and the highest training
    log-likelihood wins (ties go to the lowest seed).
    """
    from hmmlearn.hmm import GaussianHMM

    logging.getLogger("hmmlearn").setLevel(logging.ERROR)  # convergence chatter
    best, logliks = None, {}
    for seed in config.seeds:
        model = GaussianHMM(
            n_components=config.n_states,
            covariance_type=config.covariance_type,
            n_iter=config.n_iter,
            tol=config.tol,
            random_state=seed,
        )
        model.fit(x_train)
        ll = float(model.score(x_train))
        logliks[seed] = ll
        if best is None or ll > best[2]:
            best = (model, seed, ll)
    model, seed, ll = best
    return HmmParams.from_hmmlearn(model), seed, ll, logliks


def emission_logprob(params, x):
    """log p(x_t | state k) for every day and state, shape (T, K)."""
    return np.column_stack(
        [
            multivariate_normal(params.means[k], params.covars[k], allow_singular=True).logpdf(x)
            for k in range(params.n_states)
        ]
    ).reshape(len(x), params.n_states)


def filtered_probs(params, x):
    """P(state_t | x_1..x_t) for every day t, shape (T, K). No look-ahead.

    Forward algorithm in log space:
        alpha_1 = log pi + log b_1
        alpha_t = logsumexp_j(alpha_{t-1, j} + log A_jk) + log b_t(k), then normalised.
    """
    log_b = emission_logprob(params, x)
    with np.errstate(divide="ignore"):  # log(0) = -inf is fine inside logsumexp
        log_a = np.log(params.transmat)
        alpha = np.log(params.startprob) + log_b[0]
    out = np.empty_like(log_b)
    out[0] = alpha - logsumexp(alpha)
    for t in range(1, len(x)):
        alpha = logsumexp(out[t - 1][:, None] + log_a, axis=0) + log_b[t]
        out[t] = alpha - logsumexp(alpha)
    return np.exp(out)
