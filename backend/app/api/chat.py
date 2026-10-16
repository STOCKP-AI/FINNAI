"""POST /v1/chat - the AI analyst, streamed as Server-Sent Events.

Request: {"session_id": uuid?, "message": str (1-2,000 chars), "chip_id": str?}. The browser
sends only the new message; the server loads the conversation (FPD 11.5: no forged turns).

Events (FPD 14):
    tool_start {"tool", "label"}     tool_end {"tool", "ms", "ok"}     token {"text"}
    done  {"message_id", "session_id", "usage", "quota_left", "warnings", "replace_text", "label",
           "cached"}
    error {"code", "message", "session_id"}
A comment line ": ping" is sent every 15 s; a stream is capped at 90 s (SOA 5.6).
Before the stream starts, failures are normal JSON errors (429 quota, 422, 503).

Order of work, so that a refused or failed request costs nothing: the daily limit is checked
before anything is written; a chat counted against the limit is given back if anything fails
before the answer is stored. Suggestion-chip answers are generated without the visitor's own
conversation, because they are cached and shown to everyone.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.agent import guard, store
from app.agent.llm import LLMError, make_client
from app.agent.orchestrator import Final, Orchestrator, Token, ToolEnd, ToolStart
from app.agent.prompts import analyst_prompt
from app.api.schemas import ChatRequest, ErrorBody, FeedbackRequest
from app.core.client import client_hash
from app.core.config import get_settings
from app.core.errors import CODES, ApiError
from app.services import market

log = logging.getLogger("chat")
router = APIRouter(tags=["chat"])

AI_LABEL = "AI-generated · educational only"
HEARTBEAT_S = 15
STREAM_LIMIT_S = 90

CHIPS = {
    "today": "What regime is the market in today?",
    "why": "Why is the model showing this regime?",
    "history": "How has the regime changed over the last year?",
    "after_crisis": "What happened to NIFTY after past Crisis regimes?",
    "vix": "What is India VIX?",
}

_llm_override = None  # tests set a fake client here


def set_llm(client):
    global _llm_override
    _llm_override = client


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _with_heartbeat(events, interval=HEARTBEAT_S):
    """Yield events; yield None every `interval` seconds while waiting (keeps proxies open)."""
    iterator = events.__aiter__()
    pending = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield None
                continue
            task, pending = pending, None
            try:
                yield task.result()
            except StopAsyncIteration:
                return
    finally:
        if pending is not None:
            pending.cancel()


@router.post(
    "/v1/chat",
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE stream (see module docs)"},
        422: {"model": ErrorBody},
        429: {"model": ErrorBody},
        503: {"model": ErrorBody},
    },
)
async def chat(body: ChatRequest, request: Request, settings=Depends(get_settings)):
    llm_config = settings.llm()
    if llm_config.problem and _llm_override is None:
        raise ApiError("MM-CFG-001", "The AI analyst is not configured yet.")
    llm = _llm_override or make_client(llm_config, settings.llm_fallback())
    who = client_hash(request, settings)
    question = CHIPS[body.chip_id] if body.chip_id else body.message
    day = store.ist_today()  # the day the request is counted on (and refunded to)

    regime_key = None
    if body.chip_id:
        latest = (await run_in_threadpool(market.series))[0]["rows"][-1]
        regime_key = (latest["confirmed_label"], latest["date"])
        cached = await run_in_threadpool(store.cached_answer, body.chip_id, *regime_key, day)
        if cached:
            await run_in_threadpool(store.take_cached, who, settings.chat_cached_daily_limit, day)
            session_id = await run_in_threadpool(store.ensure_session, body.session_id, who)
            final = Final(text=cached["answer"], model=cached["model"])
            message_id = await run_in_threadpool(store.save_exchange, session_id, question, final, final.text)
            return _stream(_cached_events(cached, session_id, message_id))

    quota_left = await run_in_threadpool(store.take_quota, who, settings.chat_daily_limit, day)
    try:
        session_id = await run_in_threadpool(store.ensure_session, body.session_id, who)
        # A chip answer is cached for everyone: never let one visitor's conversation shape it.
        history = [] if body.chip_id else await run_in_threadpool(store.history, session_id)
    except Exception:
        await _refund(who, day)
        raise
    system = analyst_prompt(day.isoformat())
    agent = Orchestrator(llm, settings)
    events = agent.run(system, history, question)
    ctx = _Ctx(who, day, session_id, question, quota_left, body.chip_id, regime_key)
    return _stream(_agent_events(events, ctx))


@router.post(
    "/v1/feedback",
    status_code=204,
    responses={404: {"model": ErrorBody}, 422: {"model": ErrorBody}, 503: {"model": ErrorBody}},
)
async def feedback(body: FeedbackRequest, request: Request, settings=Depends(get_settings)):
    """Thumbs up / down on one AI answer of your own conversation (CHAT-09); the last click wins."""
    who = client_hash(request, settings)
    rating = 1 if body.rating == "up" else -1
    await run_in_threadpool(store.save_feedback, body.session_id, who, body.message_id, rating)
    return Response(status_code=204)


class _Ctx:
    def __init__(self, who, day, session_id, question, quota_left, chip_id, regime_key):
        self.who, self.day, self.session_id, self.question = who, day, session_id, question
        self.quota_left, self.chip_id, self.regime_key = quota_left, chip_id, regime_key


async def _refund(who, day):
    """Give a counted chat back; never raise (we may already be streaming)."""
    try:
        await run_in_threadpool(store.refund_quota, who, day)
    except Exception as exc:  # the database may be the reason we are refunding
        log.warning("Could not refund the chat (%s): %s", who[:8], exc)


def _error_event(code, session_id):
    return sse(
        "error", {"code": code, "message": CODES.get(code, (0, "Error"))[1], "session_id": str(session_id)}
    )


def _stream(generator):
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _cached_events(cached, session_id, message_id):
    for word in cached["answer"].split(" "):
        yield sse("token", {"text": word + " "})
    yield sse(
        "done",
        {
            "message_id": message_id,
            "session_id": str(session_id),
            "usage": {"in": 0, "out": 0},
            "quota_left": None,
            "warnings": [],
            "replace_text": None,
            "label": AI_LABEL,
            "cached": True,
        },
    )


async def _agent_events(events, ctx):
    session_id = ctx.session_id
    final = None
    try:
        async with asyncio.timeout(STREAM_LIMIT_S):
            async for ev in _with_heartbeat(events):
                if ev is None:
                    yield ": ping\n\n"
                elif isinstance(ev, Token):
                    yield sse("token", {"text": ev.text})
                elif isinstance(ev, ToolStart):
                    yield sse("tool_start", {"tool": ev.tool, "label": ev.label})
                elif isinstance(ev, ToolEnd):
                    yield sse("tool_end", {"tool": ev.tool, "ms": ev.ms, "ok": ev.ok})
                elif isinstance(ev, Final):
                    final = ev
    except (LLMError, TimeoutError, ApiError) as exc:
        code = getattr(exc, "code", "MM-LLM-001")
        log.warning("%s during chat (session %s): %s", code, session_id, exc)
        await _refund(ctx.who, ctx.day)
        yield _error_event(code, session_id)
        return
    except Exception:
        log.exception("Unexpected error during chat (session %s)", session_id)
        await _refund(ctx.who, ctx.day)
        yield _error_event("MM-INT-001", session_id)
        return
    if final is None:  # the model stream ended without a result
        await _refund(ctx.who, ctx.day)
        yield _error_event("MM-LLM-003", session_id)
        return

    try:
        answer, guard_warnings, replaced = guard.check(final.text)
        final.warnings += guard_warnings
        message_id = await run_in_threadpool(store.save_exchange, session_id, ctx.question, final, answer)
    except Exception as exc:
        code = exc.code if isinstance(exc, ApiError) else "MM-INT-001"
        log.warning("%s while storing the answer (session %s): %s", code, session_id, exc)
        await _refund(ctx.who, ctx.day)
        yield _error_event(code, session_id)
        return
    if ctx.chip_id and not final.warnings and ctx.regime_key:
        try:  # the answer is stored; caching it for others is only an optimisation
            await run_in_threadpool(store.cache_answer, ctx.chip_id, *ctx.regime_key, final, answer, ctx.day)
        except Exception as exc:
            log.warning("Could not cache the %s answer: %s", ctx.chip_id, exc)
    yield sse(
        "done",
        {
            "message_id": message_id,
            "session_id": str(session_id),
            "usage": {"in": final.tokens_in, "out": final.tokens_out},
            "quota_left": ctx.quota_left,
            "warnings": final.warnings,
            "replace_text": answer if replaced else None,
            "label": AI_LABEL,
            "cached": False,
        },
    )
