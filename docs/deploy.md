# Deploying the prototype (Phase 6)

Everything here is free: Render's free web service for the API, Cloudflare Pages for the
website and GitHub Actions for the nightly job. No credit card and no paid AI key are needed.

```
Browser ──► Cloudflare Pages (static React build)
   │
   └──────► Render: FastAPI in Docker (render.yaml) ──► Supabase PostgreSQL (Mumbai)
                                                   └──► Gemini (Groq when busy)
GitHub Actions: CI on every PR · nightly data pipeline + brief · keep-alive · evals · Lighthouse
```

You do the steps that need your accounts and keys; nothing in this repository contains a
secret. Keep the values in a password manager and paste them only into Render, Cloudflare and
GitHub. Never put a key in a `VITE_` variable: those ship to every browser.

## What you need

| Value | Where it comes from | Goes into |
|---|---|---|
| `DATABASE_URL` | Supabase → Connect → **Session pooler** (port 5432) | Render, GitHub secret (already there) |
| `LLM_API_KEY` | Google AI Studio → Get API key (free tier, no billing account) | Render, GitHub secret |
| `LLM_FALLBACK_API_KEY` | Groq console → API keys (free plan) | Render, GitHub secret |
| `JUDGE_API_KEY` | the same Groq key is fine | GitHub secret (evals only) |

## 1. GitHub secrets (2 minutes)

Repository → Settings → Secrets and variables → Actions → New repository secret. Add
`LLM_API_KEY`, `LLM_FALLBACK_API_KEY` and `JUDGE_API_KEY`. `DATABASE_URL` exists already.
Without the AI keys the nightly brief is written from the template, which is fine.

## 2. The API on Render (10 minutes)

1. Sign in at render.com with GitHub. Allow Render to see the `STOCKP-AI/FINNAI` repository.
2. **New → Blueprint**, pick the repository, branch `main`. Render reads `render.yaml`.
3. It asks for the four `sync: false` values:
   - `DATABASE_URL`, `LLM_API_KEY`, `LLM_FALLBACK_API_KEY`: paste them.
   - `CORS_ORIGINS`: `https://marketmood.pages.dev` (if Cloudflare gives you another address
     in step 3, change it here afterwards; exact address, no `/` at the end).
4. **Apply**. The first build takes about 5 minutes. When it is live, open
   `https://marketmood-api.onrender.com/readyz` (use the address Render shows). Expect
   `{"status":"ok","checks":{"database":"ok","model":"hmm-20261008-c2","llm":"gemini:..."}}`.

Render deploys again by itself after every merge to `main`, but only once CI is green
(`autoDeployTrigger: checksPass`) and only when API files change (`buildFilter`).

The free instance sleeps after 15 minutes without visitors and needs about a minute to wake
up; the website shows "Waking up the server…" meanwhile. Before a demo, run **Actions → Demo
warm-up** (or open `/readyz` yourself) a few minutes earlier.

## 3. The website on Cloudflare Pages (10 minutes)

1. Sign in at dash.cloudflare.com (free plan). **Workers & Pages → Create → Pages → Import an
   existing Git repository** (connect GitHub, pick `STOCKP-AI/FINNAI`).
2. Project name `marketmood` (this gives `https://marketmood.pages.dev`), production branch `main`.
3. Build settings:
   - Framework preset: React (Vite)
   - Build command: `npm run build`
   - Build output directory: `dist`
   - Root directory (advanced): `frontend`
4. Environment variables (Production):
   - `VITE_API_BASE_URL` = the Render address from step 2, e.g. `https://marketmood-api.onrender.com`
   - `NODE_VERSION` = `22`
5. **Save and Deploy**. Open the `*.pages.dev` address: the regime card should appear (after
   the wake-up message if Render was asleep).
6. Settings → Builds → Branch control: set preview branches to **None**. Preview builds would
   call the API from another address, which CORS correctly refuses.

The build writes `_headers` with the security headers, including a Content-Security-Policy
whose `connect-src` is exactly your API address. A Cloudflare build without
`VITE_API_BASE_URL` (or with an `http://` address) fails on purpose instead of publishing a
site that calls `localhost`.

If the address is not `https://marketmood.pages.dev`, put the real one in Render →
marketmood-api → Environment → `CORS_ORIGINS` and save (Render restarts the API).

## 4. Smoke test (5 minutes) — every release

- [ ] `/readyz` is ok and the dashboard shows today's regime, the brief and the chart (60D, 1Y, 5Y, Max).
- [ ] On a phone (4G): the page loads in under 3 seconds once the API is awake; no sideways scrolling.
- [ ] Chat: "What regime are we in?" streams, shows a tool chip and names a date; thumbs up works.
- [ ] "Should I buy NIFTY now?" gets a polite refusal with context, not advice.
- [ ] **Actions → Lighthouse** with the site and API addresses: mobile performance ≥ 85 and
      accessibility ≥ 95 (TC-FE-07).
- [ ] Disclaimer and the "AI-generated · educational only" label are visible.

## 5. The nightly job

`Data pipeline` runs by itself on weekdays at 19:37 IST and again at 23:07 IST: new prices,
features, regime labels (with checksum-verified model files) and the daily brief. On NSE
holidays it finds no new day and finishes normally. The second run is a no-op when the first
one worked, and it keeps an AI brief that is already written.

- First time: **Actions → Data pipeline → Run workflow** (incremental) and check the summary.
- GitHub e-mails you when a scheduled run fails. Re-run it from the Actions tab; the job is
  idempotent. GitHub turns schedules off after 60 days without commits; re-enable them there.
- Prototype exit criterion: green on 5 consecutive trading days.

## 6. Optional: UptimeRobot

A free UptimeRobot HTTP monitor on `https://<api>/livez` every 5 minutes e-mails you when the
API is down and keeps it awake during the day. One always-awake free service uses about 744 of
Render's 750 free hours a month, so do not add a second free service.

## Settings reference (Render environment)

| Variable | Value | Why |
|---|---|---|
| `TRUST_PROXY_HEADERS` | `true` | the visitor's address comes from `X-Forwarded-For` behind Render's proxy |
| `PROXY_HOPS` | `1` | how many `X-Forwarded-For` entries Render appends; the client can forge the others, so the per-visitor chat limit counts from the end (checked after the first deploy) |
| `CHAT_DAILY_LIMIT` | `10` | AI answers per visitor per IST day |
| `CHAT_GLOBAL_DAILY_LIMIT` | `300` | AI answers for all visitors together per day (protects the free AI quota; `MM-QUOTA-003`) |
| `IP_HASH_PEPPER` | generated by Render | only an HMAC of the IP is stored, never the IP |
| `NSE_HOLIDAYS` | 2026 NSE holidays | holidays are not shown as stale data; add 2027 in December |
| `LOG_LEVEL` | `INFO` | `DEBUG` for troubleshooting |

## When something is wrong

| Symptom | Check |
|---|---|
| Website: "Couldn't load the market data" with `MM-DB-001` | Supabase paused? (dashboard → Restore). `DATABASE_URL` in Render is the Session pooler string? |
| Browser console: CORS error | `CORS_ORIGINS` in Render must equal the site address exactly (https, no trailing `/`) |
| Browser console: "Refused to connect" (CSP) | `VITE_API_BASE_URL` in Cloudflare must be the Render address; redeploy the site |
| Chat answers `MM-CFG-001` | `LLM_API_KEY` missing in Render |
| Chat answers `MM-LLM-002` | Gemini and Groq both busy; try again in a minute |
| Dashboard data is a day old | Actions → Data pipeline: did the last run fail? Run it again |
| Render deploy failed | Render → Events / Logs; CI on `main` must be green first |
