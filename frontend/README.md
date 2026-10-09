# MarketMood frontend

React 19 + TypeScript + Vite, styled with Tailwind CSS 4. It talks only to the MarketMood API
([docs/api.md](../docs/api.md)), never to Supabase directly.

| Page | What it shows |
|---|---|
| `/` Dashboard | regime card (label, confidence, days in regime), today's brief + top 3 signals, NIFTY 50 chart with regime bands (60D / 1Y / 5Y / Max), four key numbers, the AI analyst (ask bar, suggested questions, streamed answers) |
| `/how-it-works` | the three regimes, how the model works, its accuracy and limits, how the AI analyst is tested |

## Run it

Needs Node.js 22 LTS (`node --version`). The backend must be running on port 8000
(`uv run uvicorn app.main:app --reload` from `backend/`); it accepts browser requests only
from `http://localhost:5173`, so keep the dev server on that port.

```
cd frontend
npm ci                      # exact versions from package-lock.json
copy .env.example .env.local   # macOS/Linux: cp .env.example .env.local
npm run dev                 # http://localhost:5173
```

| Command | What it does |
|---|---|
| `npm run dev` | dev server with hot reload |
| `npm run build` | type check + production build into `dist/` |
| `npm run preview` | serve `dist/` on http://localhost:4173 |
| `npm run lint` / `npm run typecheck` | ESLint / TypeScript |
| `npm test` | unit and component tests (Vitest + Testing Library + MSW) |
| `npm run test:e2e` | Playwright end-to-end + axe on 360 px and 1280 px (first time: `npx playwright install chromium`) |
| `npm run check` | lint + type check + unit tests |

Use `npm ci`, not `npm install`, so everyone gets the locked versions. To add a library use
`npx npm@11 install <name>@<version> --save-exact` (npm 10, which ships with Node 22, has a bug
that fails on this dependency tree) and commit `package.json` and `package-lock.json`.

## Configuration

`VITE_API_BASE_URL` (in `.env.local`, or the build environment from Phase 6) is the only
setting. Everything in a `VITE_` variable is shipped to every browser: never put a key there.

## How it is built

```
src/
  lib/api.ts         fetch wrapper: ApiError with code, message and the request id to quote
  lib/chat.ts        POST /v1/chat over SSE (@microsoft/fetch-event-source), no retries
  lib/format.ts      Indian number format, dates, regime colours
  hooks/             useRegimeToday / useRegimeHistory (TanStack Query, 5 min cache), useChat
  components/        Layout, RegimeCard, BriefPanel, StatTiles, RegimeChart, Chat, Markdown, States
  pages/             Dashboard, HowItWorks
  test/              fixtures shaped like docs/api.md, MSW server
e2e/                 Playwright tests with the API mocked (page.route), so no backend is needed
```

- **AI text is never HTML** (TC-AGT-09): `Markdown.tsx` uses react-markdown with raw HTML
  dropped and images disabled; ESLint forbids `dangerouslySetInnerHTML` and `innerHTML`.
- **Every AI answer carries** "AI-generated · educational only" (TC-AGT-11) and a footer
  disclaimer is on every page.
- **The server owns the conversation**: the browser sends only the new message and the
  `session_id`; the last 20 messages are kept in `localStorage` for display only.
- **Honest freshness**: the header pill shows which close the data is from (amber when stale)
  instead of "LIVE", because the model runs on end-of-day data.
- **Regime colours** (Bull `#199e70`, Sideways `#9085e9`, Crisis `#e66767`) were checked as a set
  on the dark background. Red and green are hard to tell apart for some colour-blind users, so a
  regime is never shown by colour alone: always with its name and icon, and the chart has a
  legend and a table view.
- **Slow first load**: after 3 s the dashboard says "Waking up the server…" (the free host sleeps).
- The chart, Markdown and How-it-works page load on demand to keep the first download small.

## Tests

| Test | Where | What it proves |
|---|---|---|
| TC-FE-01 | `Dashboard.test.tsx` | each regime shows its label, colour and confidence |
| TC-FE-02 | `Dashboard.test.tsx` | an API error shows a card with the reference and a working retry |
| TC-FE-03 | `Dashboard.test.tsx` | stale data shows a banner with the data's date |
| TC-FE-04 | `e2e/app.spec.ts` | a suggested question streams with a tool chip; Stop aborts; feedback is sent |
| TC-FE-05 | `e2e/app.spec.ts` | no sideways scroll at 360 px and 1280 px; all content reachable |
| TC-FE-06 | `e2e/app.spec.ts` | no serious or critical axe violations on both pages |
| TC-AGT-09 | `Markdown.test.tsx`, `e2e/app.spec.ts` | AI text cannot inject HTML, run scripts or load images |
| TC-AGT-11 | `e2e/app.spec.ts` | every answer is labelled as AI-generated |
| SSE contract | `lib/chat.test.ts` | events in order, pings ignored, 429 / error event / cut-off stream reported |
| TC-FE-07 | manual (Phase 6) | Lighthouse mobile: performance ≥ 85, accessibility ≥ 95, on the deployed site |

Screenshots for review: `SCREENSHOTS=1 npm run test:e2e -- screenshots` (saved in `screenshots/`).
