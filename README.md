# FINNAI / MarketMood

Agentic AI market-regime detection for Indian retail investors: an HMM on NIFTY 50
data, SHAP-based signals and an educational AI chat.

> Status: Phase 4: regime API and AI analyst ([API contract](docs/api.md),
> [decisions](docs/adr/0002-ai-analyst.md)); the real-model quality check (Gate G3) runs with
> `uv run mm-evals` once the free AI keys are set. The model `hmm-20261008-c2` is **experimental**:
> 5 of 6 reference periods, macro-F1 0.55 against the 0.60 target ([validation](docs/validation.md)).

## Repository layout

```
ml/                      data pipeline + model (Python package marketmood_ml)
  src/marketmood_ml/     common.py, check_connection.py, pipelines/{ingest,features,train,infer,nightly,register}.py
                         model/ (HMM, labels, explanations, evaluation, registry)
  models/                released model versions (JSON + LightGBM text, checksummed)
  tests/                 unit, integration and real-history tests
  pipelines/data/        Yahoo snapshot CSVs used as test fixtures
  legacy/                Phase 2 training script, kept for reference only
  notebooks/  data/      exploration notebooks; local data (not committed)
backend/                 FastAPI app (package app): regime API, AI analyst, brief, evals
  app/{api,agent,services,core}/  routes, LLM adapter + tools + tool loop, queries, settings
frontend/                web app (Phase 5; framework decision pending)
db/migrations/           numbered SQL migrations, applied in order
docs/                    project documentation
.github/workflows/       CI, Supabase keep-alive, manual data pipeline
pyproject.toml, uv.lock  workspace definition and locked versions for everyone
```

## Getting started (once per laptop)

1. **Install uv** (it also installs the right Python, 3.12):
   - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS: `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Clone and install** — creates `.venv/` with the exact versions in `uv.lock`:
   ```
   git clone https://github.com/STOCKP-AI/FINNAI.git
   cd FINNAI
   uv sync
   uv run pre-commit install
   ```
   Coming from the old setup? Delete your old `venv/` folder (the old
   `requirements.txt` files are gone) and move your `.env` from `ml/pipelines/`
   to the repository root.
3. **`.env`** in the repository root (copy `.env.example`; never commit it):
   ```
   DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```
   Use the **Session pooler** string from Supabase → Connect. The direct
   `db.<ref>.supabase.co` address is IPv6-only and does not work from GitHub Actions
   or many home networks.
4. **VS Code**: open the folder, accept the recommended extensions, and pick the
   `.venv` interpreter when asked. Formatting and import sorting run on save.
5. **LightGBM** (explanations) needs a system library: on macOS run `brew install libomp`
   once; on Windows it uses the Microsoft Visual C++ Redistributable (x64), which most
   machines already have. Check: `uv run python -c "import lightgbm"`.
6. **AI analyst keys** (free, no billing account): create `backend/.env` with `LLM_PROVIDER`,
   `LLM_API_KEY` (Google AI Studio), `LLM_FALLBACK_PROVIDER=groq` + `LLM_FALLBACK_API_KEY` (used
   when Gemini is busy), `JUDGE_PROVIDER=groq`, `JUDGE_API_KEY` (Groq) and `IP_HASH_PEPPER` -
   see `.env.example`. Without keys, `LLM_PROVIDER=mock` works offline.

## Daily commands

```
uv run mm-check-db                 # connection type (never the password) + row counts
uv run mm-ingest --dry-run         # download and check NIFTY + VIX, write nothing
uv run mm-ingest                   # incremental: last stored date - 5 days -> today
uv run mm-ingest --full            # reload 10 years
uv run mm-features                 # recompute features
uv run mm-infer                    # regime labels for every day with the active model
uv run mm-nightly                  # ingest -> features -> labels, logged in pipeline_runs
uv run mm-train                    # retrain: pre-registered sweep, report (see ml/models/README.md)
uv run mm-register ml/models/<version>  # make a committed model the active one (fresh database)
uv run pytest                      # all tests (integration tests skip without a test DB)
uv run ruff check . ; uv run ruff format .
uv run uvicorn app.main:app --reload   # API on http://localhost:8000 (docs at /docs)
uv run mm-brief                    # today's dashboard brief (AI, checked; template fallback)
uv run mm-evals                    # golden questions -> docs/evals.md (needs AI keys)
```

Adding a library: `uv add --package marketmood-ml <name>` (or `marketmood-backend`),
then commit both `pyproject.toml` and `uv.lock`.

Exit codes: 0 success (including "no new data" on holidays); 1 known failure with an
`MM-*` code in the log; 2 unexpected error or a wrong command-line option.

| Code | Meaning |
|---|---|
| `MM-CONFIG-001` | `DATABASE_URL` missing |
| `MM-DATA-002` | data-quality check failed; nothing was written |
| `MM-DATA-003` | Yahoo Finance download failed after 3 retries |
| `MM-DB-001` | database connection or query failed (check `DATABASE_URL`, use the pooler) |
| `MM-MODEL-001` | a model file is missing or its checksum differs; inference refused |
| `MM-MODEL-002` | a new model missed a gate; not registered, the active model is kept |
| `MM-MODEL-003` | no active model in `model_registry` |
| `MM-MODEL-004` | a model version already exists with different files |
| `MM-CONFIG-002` | LightGBM could not load its system library (see Getting started, step 5) |

API and chat codes (`MM-REQ-*`, `MM-QUOTA-001`, `MM-LLM-*`, `MM-TOOL-001`, `MM-CFG-001`) are
listed in [docs/api.md](docs/api.md).

## Tests

| Test | What it proves |
|---|---|
| TC-DATA-01 | running ingest twice changes nothing — with fakes, and end to end on Postgres in CI |
| TC-DATA-02 | a yfinance multi-level response is parsed; `Close`, never `Adj Close`; `auto_adjust=False` |
| TC-DATA-03 | on a market holiday the run logs "No new data" and exits 0 |
| TC-DATA-04 | `drawdown_60d` = close / rolling 60-day max − 1 |
| TC-DATA-05 | no NaN after warm-up; exactly the first 60 rows dropped |
| TC-DATA-06 | a source timeout is retried 3 times (2 s, 4 s, 8 s), then `MM-DATA-003` |
| TC-DATA-07 | a close of 0 blocks the write with `MM-DATA-002` |
| Real history | the 17 days the old inner join dropped are recovered; features equal the values stored in Supabase |
| TC-ML-01 | a 3-regime synthetic series is recovered (>= 90% of days) |
| TC-ML-02 | probabilities for day t are identical with or without later days (no look-ahead) |
| TC-ML-03 | training twice with the same seeds gives identical files |
| TC-ML-04 | state names follow the market (any state numbering); a crash before a rebound stays Crisis |
| TC-ML-05 | the released model gets >= 5 of 6 reference periods on the real snapshot |
| TC-ML-06 | macro-F1 and confusion matrix are saved; the status follows the gates |
| TC-ML-07 | surrogate fidelity >= 95% (synthetic and real data) |
| TC-ML-08 | a changed or missing model file is refused with `MM-MODEL-001` (unit and end to end) |
| TC-ML-09 | a one-day flip does not change the confirmed label |
| TC-ML-11 | the backtest changes with an extra day of delay and reruns are identical |
| Idempotency | `mm-infer` twice writes nothing the second time; `mm-nightly` logs one `pipeline_runs` row |
| TC-API-01…06, 08 | today's card (as_of, is_stale), stale data, history ≤ 500 points, 422 on bad range, 413 on big bodies, exact CORS, OpenAPI snapshot |
| TC-AGT-01…10 | tool use, refusals and injection (mock + evals), numbers grounded, tool errors, 5-round cap, server-side history, image stripping, brief number check |

Integration tests need `TEST_DATABASE_URL` pointing at a **disposable** Postgres with the
migrations applied (CI does this automatically); they refuse to run against Supabase.

## GitHub Actions

| Workflow | When | Needs |
|---|---|---|
| CI | every pull request and push to `main`: lockfile, ruff, migrations on Postgres 17, tests with coverage (ml ≥ 85%, backend ≥ 80%) | nothing |
| Supabase keep-alive | Monday and Thursday 08:47 IST, or manually | secret `DATABASE_URL` |
| Data pipeline | manually (Actions → Data pipeline → Run workflow); nightly from Phase 6. Does not refresh `regime_output` yet: run `uv run mm-infer` afterwards | secret `DATABASE_URL` |

Add the secret under Settings → Secrets and variables → Actions → New repository
secret, name `DATABASE_URL`, value = the Session pooler string.

## Database changes

All schema changes go in `db/migrations/` as new numbered files — see
[db/migrations/README.md](db/migrations/README.md).

## Team workflow

- Never commit to `main` (pre-commit blocks it): create a branch, open a pull request,
  wait for CI and one review.
- Never commit `.env`, passwords or API keys (pre-commit blocks `.env` files and private keys).
