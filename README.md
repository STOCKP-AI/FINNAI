# FINNAI / MarketMood

Agentic AI market-regime detection for Indian retail investors: an HMM on NIFTY 50
data, SHAP-based signals and an educational AI chat.

> Status: Phase 2.5 done (data-pipeline fixes, tooling, CI). The rows in `regime_output`
> are tagged `HMM_v1-placeholder` until Phase 3 — do not present them as model output.

## Repository layout

```
ml/                      data pipeline + model (Python package marketmood_ml)
  src/marketmood_ml/     common.py, check_connection.py, pipelines/{ingest,features}.py
  tests/                 unit, integration and real-history tests
  pipelines/data/        Yahoo snapshot CSVs used as test fixtures
  legacy/                Phase 2 training script, kept for reference only
  notebooks/  data/      exploration notebooks; local data (not committed)
backend/                 FastAPI app (package app); only /livez until Phase 4
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

## Daily commands

```
uv run mm-check-db                 # connection type (never the password) + row counts
uv run mm-ingest --dry-run         # download and check NIFTY + VIX, write nothing
uv run mm-ingest                   # incremental: last stored date - 5 days -> today
uv run mm-ingest --full            # reload 10 years
uv run mm-features                 # recompute features
uv run pytest                      # all tests (integration tests skip without a test DB)
uv run ruff check . ; uv run ruff format .
uv run uvicorn app.main:app --reload   # API on http://localhost:8000/livez
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

Integration tests need `TEST_DATABASE_URL` pointing at a **disposable** Postgres with the
migrations applied (CI does this automatically); they refuse to run against Supabase.

## GitHub Actions

| Workflow | When | Needs |
|---|---|---|
| CI | every pull request and push to `main`: lockfile, ruff, migrations on Postgres 17, tests with coverage (ml ≥ 85%, backend ≥ 80%) | nothing |
| Supabase keep-alive | Monday and Thursday 08:47 IST, or manually | secret `DATABASE_URL` |
| Data pipeline | manually (Actions → Data pipeline → Run workflow); nightly from Phase 6 | secret `DATABASE_URL` |

Add the secret under Settings → Secrets and variables → Actions → New repository
secret, name `DATABASE_URL`, value = the Session pooler string.

## Database changes

All schema changes go in `db/migrations/` as new numbered files — see
[db/migrations/README.md](db/migrations/README.md).

## Team workflow

- Never commit to `main` (pre-commit blocks it): create a branch, open a pull request,
  wait for CI and one review.
- Never commit `.env`, passwords or API keys (pre-commit blocks `.env` files and private keys).
