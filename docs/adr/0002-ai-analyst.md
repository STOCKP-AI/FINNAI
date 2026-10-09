# ADR 0002: Phase 4 backend API and AI analyst

Status: accepted for the prototype, 9 Oct 2026. Contract: [api.md](../api.md).

## Context

The prototype needs a dashboard API and an AI analyst that answers from MarketMood's own data,
never gives personal investment advice, and costs nothing to run (no paid AI key, Prototype
Build Plan v2.1 section 8.3). The team is small and the laptops are modest.

## Decisions

- **FastAPI + psycopg pool, read-only by default.** Public endpoints and every AI tool run in a
  READ ONLY transaction as the `agent_reader` role (migration 005): SELECT on market tables only,
  through explicit RLS policies; no access to chat data. Writes (chat, quota, cache) use a normal
  transaction. The pool opens in the background so `/livez` works when the database is down.
- **Regime endpoints from the database only** (no Yahoo calls per request), cached 5 minutes;
  `is_stale` against the last closed NSE session (weekday rule plus an `NSE_HOLIDAYS` list);
  if the database fails after a good read, the last good data is served marked stale.
- **Provider-neutral LLM adapter.** `OpenAICompatClient` (Gemini free tier by default, Groq as
  backup, GitHub Models possible) and `MockClient`. The adapter keeps Gemini 3's thought
  signatures and sends them back, which Gemini requires for multi-step tool use. Claude is
  added in Phase 7 as another client; tools, prompts and tests stay the same.
- **Mock model is a real fallback.** It picks tools by keyword and writes templated answers
  from real tool results, so the frontend team and the demo work without any key, and it
  passes all 20 golden-set rule checks.
- **7 tools, strict and small.** Arguments are validated in code (the model is not trusted);
  results are rounded JSON; a failed tool tells the model "unavailable" (MM-TOOL-001) instead
  of raising. History for the LLM is downsampled to 120 points.
- **Busy providers.** Free tiers answer HTTP 503 (overloaded) and 429 (rate limit) often. The
  adapter retries a call that has produced nothing yet (after 2 s and 6 s, or the provider's own
  retry delay up to 10 s), then switches to the fallback model (`LLM_FALLBACK_*`, Groq) for the
  rest of that request; Gemini's thought signatures are removed from what the fallback sees.
  `mm-evals` waits 45 s and retries a question once; a question the provider still cannot answer
  is "not evaluated" and the run is INCOMPLETE, not a quality failure.
- **Tool loop** up to 5 rounds, then one answer without tools (MM-LLM-004); answers stream as
  SSE with tool activity, a 15-second heartbeat and a 90-second cap.
- **Server-side history.** The client sends only `session_id` + the new message (unknown fields
  are refused); the last 10 messages come from `chat_messages`. A session id from a different
  client starts a new session, so ids cannot be used to read someone else's chat.
- **Guard after streaming.** Images and HTML images removed, e-mails and key-like strings
  redacted; directive advice, price targets or a leaked prompt (canary marker) replace the
  stored answer, and `done.replace_text` tells the UI (MM-LLM-005).
- **Protection without accounts.** 10 chats per visitor per IST day, keyed by
  HMAC-SHA256(pepper, IP); the IP itself is never stored. The chat is refunded when the AI fails.
  Suggestion-chip answers are cached per day and regime and do not count. Bodies: 16 KB chat,
  1 KB elsewhere; messages 2,000 characters.
- **Daily brief** (`mm-brief`): one AI call per day, accepted only if every number is one of the
  given facts (within 0.1), no advice words, 30-90 words; otherwise a template brief.
- **Evals** (`mm-evals`): 20 golden questions to start (the plan allows 20 now, 40 by Phase 6),
  rule checks (tools, forbidden/required patterns, length, every number grounded in tool data,
  no prompt leak) and a judge from a different provider (Groq judges Gemini).
- **Dependencies** added to the backend: openai (client only), psycopg-pool, cachetools,
  pydantic-settings; pyyaml for evals (dev). New versions were limited to releases at least 14
  days old. numpy is not needed in the backend.
- The ML pipelines and the API now read floats at full precision (`extra_float_digits = 3`);
  the Supabase server default sends 15 digits.

## Deviations from the plan

- Langfuse tracing and Sentry are not wired yet (they need accounts and keys); request ids and
  structured logs are in place. Revisit in Phase 6 with deployment.
- Usage is limited per IP (prototype), not per user; accounts and plan quotas come in Phase 7.
- The eval workflow (`evals.yml`) is not added: the connector cannot edit workflows, and evals
  need the free-tier keys, so they run on a laptop for now.

## Privacy

Free-tier prompts may be used by the provider to improve its products. Prompts contain only the
question, the conversation and market data - no names, e-mails or account data (the prototype
has no accounts). The About page must say this (Phase 5).
