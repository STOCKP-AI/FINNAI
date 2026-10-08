"""Market-regime model (Phase 3): causal Gaussian HMM, automatic labels, LightGBM explanations.

config.py      pre-registered configurations, reference periods, gates
hmm.py         transform, scaling, training over seeds, forward filtering
labeling.py    state names and the 2-day confirmation rule
explain.py     surrogate model and TreeSHAP signals
evaluation.py  reference labels, periods, macro-F1, stability, transition lag, gates
backtest.py    regime-aware allocation vs buy-and-hold
trainer.py     one configuration end to end, the sweep and the selection rule
predict.py     model + features -> one regime_output row per day (training and inference)
artifacts.py   pickle-free model files with SHA-256 checksums
registry.py    model_registry and pipeline_runs
report.py      docs/validation.md and the validation chart
"""
