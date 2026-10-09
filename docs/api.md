# MarketMood API (v1) — contract for the frontend

Base URL in development: `http://localhost:8000` (`uv run uvicorn app.main:app --reload`).
Interactive docs: `/docs`; machine-readable contract: `/openapi.json` (snapshot in
`backend/tests/openapi.json`, checked by TC-API-08). Only these browser origins may call
the API: `http://localhost:5173` (Vite dev server) and, from Phase 6, the deployed site.

The regime samples below are real responses from the 8 Oct 2026 data (lists shortened).

## Errors (every endpoint)

```json
{"error": {"code": "MM-REQ-001", "message": "The request is not valid.", "request_id": "92319713fa1e495fa4c9438a133e6a27",
           "details": [{"field": "range", "problem": "Input should be '60d', '1y', '5y' or 'max'"}]}}
```

| Status | Code | When |
|---|---|---|
| 413 | MM-REQ-002 | body over 16 KB (chat) or 1 KB (anything else) |
| 422 | MM-REQ-001 | invalid parameter or body (also unknown fields) |
| 429 | MM-QUOTA-001 | 10 chats per visitor per day used (resets at midnight IST) |
| 503 | MM-DB-001 / MM-CFG-001 | database unreachable / AI not configured |

Show `request_id` in error messages ("Reference: …"); every response also has an
`X-Request-ID` header.

## GET /v1/regime/today

Cached 5 minutes (`Cache-Control: public, max-age=300`).

```json
{
  "as_of": "2026-10-08",
  "is_stale": false,
  "regime": {"label": "Sideways", "raw_label": "Sideways", "confidence": 0.9972,
             "probabilities": {"bull": 0.0, "sideways": 0.9972, "crisis": 0.0028},
             "days_in_regime": 20, "since": "2026-09-09"},
  "signals": [
    {"feature": "volatility_20d", "name": "Volatility (20 days)", "value": 0.00799118, "direction": "up",
     "text": "Daily price swings are larger than usual", "contribution": 0.9726, "percentile": 58.9}
  ],
  "signals_approximate": false,
  "brief": {"text": "NIFTY 50 closed at 22,231.80 on 2026-10-08 (-1.64%). MarketMood's model reads the market as Sideways, ...",
            "what_changed": "No regime change since the previous trading day.", "source": "template"},
  "nifty": {"as_of": "2026-10-08", "close": 22231.8, "change_pct": -1.64, "high_52w": 26328.55,
            "low_52w": 22231.8, "from_high_pct": -15.56, "ytd_pct": -14.92},
  "model": {"version": "hmm-20261008-c2", "status": "experimental"},
  "disclaimer": "Educational information about market conditions, not investment advice.",
  "warnings": []
}
```

- `regime.label` is what to show (it changes only after 2 days in a row); `raw_label` is
  today's most likely regime and differs from `label` while a change is being confirmed.
- `confidence` is the model's own probability for `label`. It is overconfident: show it as
  "how sure the model is", never as a chance of anything happening.
- `is_stale: true` (with warning `MM-DATA-001`) means the latest data is older than the last
  trading session: show a "data from <as_of>" banner.
- `signals_approximate: true` means the explanation model disagreed with the main model
  today: show the signals with "approximate".
- `model.status: "experimental"`: show a small "experimental model" badge (see docs/validation.md).

## GET /v1/regime/history?range=60d|1y|5y|max

At most 500 points, oldest first. `label` is the confirmed label (use it for chart colours).

```json
{"range": "60d", "as_of": "2026-10-08",
 "points": [{"date": "2026-08-10", "label": "Bull", "confidence": 0.9999, "close": 24583.8},
            {"date": "2026-10-08", "label": "Sideways", "confidence": 0.9972, "close": 22231.8}]}
```

## GET /v1/regime/episodes?regime=Bull|Sideways|Crisis&limit=1..100

Past stretches of one confirmed regime, most recent first (all regimes if `regime` is omitted).

```json
{"regime": "Crisis", "as_of": "2026-10-08",
 "episodes": [{"regime": "Crisis", "start": "2026-03-13", "end": "2026-04-30", "days": 31,
               "nifty_change_pct": 3.66, "max_drawdown_pct": -6.08, "ongoing": false}]}
```

## POST /v1/chat (Server-Sent Events)

Request (JSON, at most 16 KB). The browser sends only the new message; the server keeps the
conversation. Keep the `session_id` from the `done` event and send it with the next message.

```json
{"session_id": "8a0f3c2e-…-…", "message": "What regime is the market in today?", "chip_id": null}
```

Suggestion chips (`chip_id`, the server uses the fixed question; answers are cached for the
day and do not count against the limit): `today`, `why`, `history`, `after_crisis`, `vix`.

Response: `Content-Type: text/event-stream`. Events, in order (numbers in this example are illustrative):

```
event: tool_start
data: {"tool": "get_current_regime", "label": "Checking today's regime"}

event: tool_end
data: {"tool": "get_current_regime", "ms": 84, "ok": true}

event: token
data: {"text": "As of 2026-10-08, the model reads the market as "}

event: done
data: {"message_id": 812, "session_id": "8a0f3c2e-…", "usage": {"in": 2140, "out": 312}, "quota_left": 9,
       "warnings": [], "replace_text": null, "label": "AI-generated · educational only", "cached": false}
```

- Append `token` texts in order. Show `tool_start.label` as a status line until `tool_end`.
- If `done.replace_text` is not null, replace the whole message with it (a safety check
  rewrote the answer, warning `MM-LLM-005`).
- Always show `done.label` ("AI-generated · educational only") under AI messages (TC-AGT-11).
- Render AI text as Markdown **without images and without raw HTML** (TC-AGT-09).
- `event: error` → `{"code": "MM-LLM-002", "message": "The AI analyst is busy - try again in a minute.", "session_id": "…"}`.
  The chat is not counted against the limit when the AI fails.
- Lines starting with `:` (`: ping`, every 15 s) are keep-alives: ignore them. A stream ends
  after 90 s at most.
- Before the stream starts, failures are normal JSON errors (429, 422, 503).

## POST /v1/feedback

Thumbs up / down on one AI answer (CHAT-09). Use the `session_id` and `message_id` from the
chat's `done` event. A second click replaces the first.

```json
{"session_id": "8a0f3c2e-…", "message_id": 812, "rating": "up"}
```

`204 No Content` on success; `404 MM-REQ-003` if that answer is not in your own conversation;
`422` for anything else in the body.

## Health

`GET /livez` → `{"status": "ok", "version": "0.2.0"}` (no dependencies).
`GET /readyz` → 200 `{"status": "ok", "checks": {"database": "ok", "model": "hmm-20261008-c2", "llm": "gemini:gemini-3.8-flash"}}`, or 503 with `"status": "degraded"`.
