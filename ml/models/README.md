# Released models

One folder per released version, named `hmm-<last data date>-<configuration>`:

| File | Contents | Needed to run |
|---|---|---|
| `model.json` | scaler, HMM parameters, state names, feature medians, training range | yes |
| `surrogate.txt` | LightGBM text model for the explanations | yes |
| `metrics.json` | every evaluation result (also in `docs/validation.md`) | no |

No pickle files: loading a pickle can run arbitrary code. The SHA-256 of `model.json` and
`surrogate.txt` is stored in the database (`model_registry.checksums`); `mm-infer` refuses
to run if a file differs (MM-MODEL-001). Never edit these files by hand, and never reuse a
version name for different files (`mm-train` refuses: MM-MODEL-004).

Release a new model:

```
uv run mm-train                                   # sweep, pick, save, write docs/validation.md
uv run mm-train --register --allow-experimental   # same, then make it the active model
uv run mm-infer                                   # rewrite regime_output with the active model
```

A fresh database (for example a teammate's local Postgres) can use a model that is already
in Git: `uv run mm-register ml/models/<version>`, then `uv run mm-infer`.

Commit the new folder and `docs/validation.md` in the same pull request. Which version is
live is decided by `model_registry` (exactly one row with `is_active = true`), not by Git.
