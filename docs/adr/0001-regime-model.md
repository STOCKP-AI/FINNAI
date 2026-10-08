# ADR 0001: Phase 3 regime model

Status: accepted for the prototype, 8 Oct 2026. Results: [validation.md](../validation.md).

## Context

The Phase 2 output in `regime_output` was a placeholder: Viterbi labels that used future
data, a fixed 0.85 confidence and hard-coded signals (audit A2). Phase 3 replaces it with a
model whose daily label only ever uses data up to that day, and whose quality is measured
against objective criteria fixed in advance (Prototype Build Plan v2.1 section 7).

## Decision

- **Model.** Gaussian HMM, 3 states, on the 8 features (fii_flow stays excluded: it is
  always 0). Scaler and HMM are fitted on training days only (everything up to 24 months
  before the last date); 10 seeds, best training log-likelihood.
- **Causal labels.** `filtered_probs()` (forward algorithm) is the only path from data to
  labels: P(state on day t | days 1..t). `predict()` / `predict_proba()` are never used.
  A change of label is confirmed after 2 consecutive days (`confirmed_label` is what users
  see; `confidence` is the probability of that label).
- **State names from trailing, not forward, returns.** The Build Plan sketch named states by
  their mean *forward* 20-day return. On the real data the crash state is followed by the
  rebound, so it had the highest forward return and the COVID crash was named "Bull" (run C0:
  2 of 6 reference periods). Using the *trailing* 20-day return fixes this and means no future
  data is used anywhere: Crisis = highest-volatility state if its trailing return is negative
  (else the lowest-return state), Bull = highest trailing return of the rest, else Sideways.
- **Log-transform** of volatility_20d, vix_level, bb_width (log) and vix_change_30d (log1p):
  on the training data their skewness is 4 to 6.6, which breaks Gaussian emissions (one state
  ends up holding only the 26 days of March 2020).
- **Pre-registered sweep.** Seven configurations (C1-C7 in `model/config.py`), the reference
  labels, the period scoring, the gates and the selection rule were written down before the
  final run: the first configuration passing every gate; if none does, the most reference
  periods correct, then the highest macro-F1. Every configuration is reported.
- **Objective reference labels** (evaluation only; they look 20 days either side): Crisis if
  the close is 10% or more below its 252-day high and VIX >= 25; else Bull if the close 20
  days later is 2% or more above the close 20 days earlier; else Sideways.
- **Explanations.** A LightGBM surrogate imitates the HMM's daily label; LightGBM's own
  TreeSHAP gives each day's top 3 features for the label shown. 10 trees x 15 leaves: the
  same fidelity as the plan's 200 trees (99%, 92% out of sample) in a 46 KB text file instead
  of 886 KB. `surrogate_agrees` marks days where it disagrees with the HMM.
- **Pickle-free artifacts.** `ml/models/<version>/` holds JSON and LightGBM text, LF line
  endings, with SHA-256 checksums stored in `model_registry`; a changed file is refused
  (MM-MODEL-001) and a released version is never overwritten (MM-MODEL-004).
- **No MLflow for the prototype** (allowed by plan item M13): the sweep is logged in
  `metrics.json`, `validation.md` and the training log. Revisit with weekly retraining (Phase 8).

## Result

Released `hmm-20261008-c2` (log-transform, diagonal covariance), status **experimental**:
5 of 6 reference periods, surrogate fidelity 99.3%, 4.1 confirmed switches a year on the test
period, the March 2020 crash flagged on its first day; but macro-F1 against the reference
labels is 0.55, below the 0.60 target. No configuration met every gate. Accepted for the
prototype by the product owner on 8 Oct 2026, with the miss reported.

## Known limitations

- The model separates calm, normal and stressed markets well; it is weaker at telling a calm
  uptrend from a flat market. It calls the post-COVID rally (Jun 2020 - Oct 2021) Sideways.
  A simple rule (VIX/drawdown for Crisis, positive 60-day Sharpe for Bull) scores a higher
  macro-F1 (0.66) against the same reference labels.
- The six reference periods fall inside the training window, so that check is in-sample
  (labels are causal, parameters are not). The walk-forward check (refit each year on
  earlier years only) is fully out of sample: 3 of 4 periods, macro-F1 0.47.
- Probabilities are overconfident (mean 0.97); show them as "how sure", not as a chance.
- NIFTY is the price index (no dividends); the backtest is a research result, not advice.

## Next

Improve the Bull/Sideways split (for example a trend feature on a longer window, or 4 states)
as a new pre-registered sweep, logged as new runs, before Release 1.0.
