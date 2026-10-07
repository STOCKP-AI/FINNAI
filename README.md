# FINNAI / MarketMood

Agentic AI market-regime detection for Indian retail investors: an HMM on NIFTY 50
data, SHAP-based signals and an educational AI chat.

> Status: Phase 2.5 (audit fixes for the data pipeline). The model in
> `regime_output` is a placeholder until Phase 3 — do not present it as model output.

## Repository layout

```
db/migrations/       numbered SQL migrations (001 = live schema baseline)
ml/pipelines/        data pipeline: ingest -> features -> training
ml/tests/            unit tests for the pipeline (no network, no database)
backend/             FastAPI app (Phase 4)
frontend/            web app (Phase 5)
docs/                project documentation
```

## Getting started (data pipeline)

This uses your existing Python environment; nothing new needs installing.

1. **`.env`** — keep it where it is today (`ml/pipelines/`, `ml/` or the repository
   root all work; the scripts search upwards from `ml/pipelines/`). Never commit it.

   ```
   DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```

   Use the **Session pooler** string from Supabase → Connect. The direct
   `db.<ref>.supabase.co` address is IPv6-only and will not work from GitHub Actions
   or many home networks.

2. **Check the connection** — prints the connection type (never the password) and
   row counts:

   ```
   python ml/pipelines/check_connection.py
   ```

3. **Update market data** (incremental: last stored date − 5 days → today):

   ```
   python ml/pipelines/ingest.py --dry-run   # download and check only (still reads the last date from the DB)
   python ml/pipelines/ingest.py             # write to market_data
   python ml/pipelines/ingest.py --full      # reload 10 years (fills the 17 days the old inner join dropped), then run step 4
   ```

4. **Recompute features**:

   ```
   python ml/pipelines/feature_pipeline.py --dry-run
   python ml/pipelines/feature_pipeline.py
   ```

Exit code 0 means success (including "no new data" on holidays); 1 means a known
failure whose `MM-*` code is in the log; 2 means an unexpected error or a wrong
command-line option.

| Code | Meaning |
|---|---|
| `MM-CONFIG-001` | `DATABASE_URL` missing |
| `MM-DATA-002` | data-quality check failed; nothing was written |
| `MM-DATA-003` | Yahoo Finance download failed after 3 retries |
| `MM-DB-001` | database connection or query failed (check `DATABASE_URL`, use the pooler) |

## Running the tests

From the `ml/` folder:

```
cd ml
python -m unittest discover -s tests -v
```

The tests use synthetic data and fakes, so they need no internet and no database.

| Test | What it proves |
|---|---|
| TC-DATA-01 | running ingest twice changes nothing (upsert on date) |
| TC-DATA-02 | a yfinance 1.3 response with multi-level columns is parsed; `Close`, never `Adj Close`; `auto_adjust=False` |
| TC-DATA-03 | on a market holiday the run logs "No new data" and exits 0 |
| TC-DATA-04 | `drawdown_60d` = close / rolling 60-day max − 1 |
| TC-DATA-05 | no NaN after warm-up; exactly the first 60 rows dropped |
| TC-DATA-06 | a source timeout is retried 3 times (2 s, 4 s, 8 s), then `MM-DATA-003` |
| TC-DATA-07 | a close of 0 blocks the write with `MM-DATA-002` |

## Database changes

All schema changes go in `db/migrations/` as new numbered files — see
[db/migrations/README.md](db/migrations/README.md). `db/schema/schema.sql` was
removed because it no longer matched the database.

## Team workflow

- Never push straight to `main`: create a branch, open a pull request, get one review.
- Never commit `.env`, passwords or API keys.
