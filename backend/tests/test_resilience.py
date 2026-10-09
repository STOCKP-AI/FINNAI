"""Busy free-tier providers: retries, fallback model, retry delays, eval runs that cannot finish."""

import asyncio
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.agent.llm import (
    Done,
    LLMError,
    OpenAICompatClient,
    ResilientClient,
    TextDelta,
    ToolCall,
    _retry_after,
    _without_provider_extras,
    make_client,
)
from app.core.config import LLMConfig
from app.evals import run as evals
from backend_helpers import make_settings

KEY = SimpleNamespace(get_secret_value=lambda: "k")


def collect(agen):
    async def go():
        return [ev async for ev in agen]

    return asyncio.run(go())


class Scripted:
    """Each call plays the next item: an LLMError raised before any output, or a list of events
    (an LLMError inside the list is raised after the events before it)."""

    def __init__(self, model, script):
        self.model, self.provider, self.script, self.seen = model, "test", list(script), []

    async def stream(self, system, messages, tools=None):
        self.seen.append(messages)
        item = self.script.pop(0)
        if isinstance(item, LLMError):
            raise item
        for ev in item:
            if isinstance(ev, LLMError):
                raise ev
            yield ev


BUSY = LLMError("MM-LLM-002", "HTTP 503", retryable=True)
ANSWER = [TextDelta("ok"), Done("stop")]


def resilient(primary, fallback=None, **kw):
    waits = []

    async def sleep(s):
        waits.append(s)

    return ResilientClient(primary, fallback, sleep=sleep, **kw), waits


def test_busy_provider_is_retried_then_answers():
    primary = Scripted("gemini", [BUSY, BUSY, ANSWER])
    client, waits = resilient(primary)
    assert [e.text for e in collect(client.stream("s", [])) if isinstance(e, TextDelta)] == ["ok"]
    assert waits == [2.0, 6.0] and client.model == "gemini"


def test_fallback_answers_after_retries_and_stays_for_the_request():
    sig = {"google": {"thought_signature": "S"}}
    history = [{"role": "assistant", "content": None, "tool_calls": [{"id": "1", "extra_content": sig}]}]
    primary = Scripted("gemini", [BUSY, BUSY, BUSY])
    fallback = Scripted("gpt-oss", [ANSWER, ANSWER])
    client, waits = resilient(primary, fallback)
    assert collect(client.stream("s", history))[0] == TextDelta("ok")
    assert client.model == "gpt-oss" and waits == [2.0, 6.0]
    assert "extra_content" not in fallback.seen[0][0]["tool_calls"][0]  # Gemini-only field removed
    assert history[0]["tool_calls"][0]["extra_content"] == sig  # caller's history untouched
    collect(client.stream("s", []))  # next round goes straight to the fallback
    assert len(primary.seen) == 3 and len(fallback.seen) == 2


def test_long_retry_delay_skips_waiting():
    slow = LLMError("MM-LLM-002", "rate limited", retry_after_s=37.0, retryable=True)
    primary, fallback = Scripted("gemini", [slow]), Scripted("gpt-oss", [ANSWER])
    client, waits = resilient(primary, fallback)
    collect(client.stream("s", []))
    assert waits == [] and client.model == "gpt-oss"


def test_short_retry_delay_is_honoured():
    soon = LLMError("MM-LLM-002", "rate limited", retry_after_s=3.0, retryable=True)
    client, waits = resilient(Scripted("gemini", [soon, ANSWER]))
    collect(client.stream("s", []))
    assert waits == [3.0]


def test_no_retry_after_output_or_for_bad_requests():
    client, _ = resilient(Scripted("gemini", [[TextDelta("par"), BUSY]]), Scripted("f", [ANSWER]))
    with pytest.raises(LLMError):
        collect(client.stream("s", []))  # an answer is never repeated
    bad = LLMError("MM-LLM-003", "HTTP 400")
    client, waits = resilient(Scripted("gemini", [bad]), Scripted("f", [ANSWER]))
    with pytest.raises(LLMError) as ctx:
        collect(client.stream("s", []))
    assert ctx.value is bad and waits == []


def test_everything_busy_raises_the_last_error():
    client, _ = resilient(Scripted("g", [BUSY] * 3), Scripted("f", [BUSY] * 3))
    with pytest.raises(LLMError) as ctx:
        collect(client.stream("s", []))
    assert ctx.value.retryable


def test_tool_calls_pass_through():
    call = ToolCall("1", "get_nifty_stats", "{}")
    client, _ = resilient(Scripted("g", [[call, Done("tool_calls")]]))
    assert collect(client.stream("s", []))[0] is call


def error(cls, status, body=None, headers=None):
    response = httpx2.Response(status, request=httpx2.Request("POST", "http://x"), headers=headers or {})
    return cls("provider error", response=response, body=body)


def test_retry_delay_from_header_and_gemini_body():
    assert _retry_after(error(openai.RateLimitError, 429, headers={"retry-after": "7"})) == 7.0
    body = {"message": "Quota exceeded for metric ... per minute", "details": [{"retryDelay": "37s"}]}
    assert _retry_after(error(openai.RateLimitError, 429, body=body)) == 37.0
    assert _retry_after(error(openai.InternalServerError, 503)) is None


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (500, True), (400, False)])
def test_adapter_marks_retryable_errors_with_provider_hint(status, retryable):
    cls = openai.RateLimitError if status == 429 else openai.APIStatusError
    exc = error(cls, status, body={"message": "Quota exceeded for metric requests per day"})

    class Fails:
        async def create(self, **_):
            raise exc

    client = OpenAICompatClient(
        LLMConfig("gemini", None, None, KEY, 5),
        client=SimpleNamespace(chat=SimpleNamespace(completions=Fails())),
    )
    with pytest.raises(LLMError) as ctx:
        collect(client.stream("s", []))
    assert ctx.value.retryable is retryable
    assert "gemini" in ctx.value.message and "per day" in ctx.value.message


def test_connection_errors_and_timeouts_are_retryable():
    for exc in (
        openai.APIConnectionError(request=httpx2.Request("POST", "http://x")),
        openai.APITimeoutError(request=httpx2.Request("POST", "http://x")),
    ):

        class Fails:
            async def create(self, **_):
                raise exc  # noqa: B023

        client = OpenAICompatClient(
            LLMConfig("groq", None, None, KEY, 5),
            client=SimpleNamespace(chat=SimpleNamespace(completions=Fails())),
        )
        with pytest.raises(LLMError) as ctx:
            collect(client.stream("s", []))
        assert ctx.value.retryable


def test_make_client_with_and_without_fallback():
    gemini = LLMConfig("gemini", None, None, KEY, 5)
    groq = LLMConfig("groq", None, None, KEY, 5)
    with_fb = make_client(gemini, groq)
    assert isinstance(with_fb, ResilientClient) and with_fb.fallback.model == "openai/gpt-oss-120b"
    assert with_fb.model == gemini.model and with_fb.provider == "gemini"
    assert make_client(gemini, LLMConfig("groq", None, None, None, 5)).fallback is None  # no key
    assert make_client(gemini, None).fallback is None


def test_settings_read_the_fallback():
    s = make_settings(llm_fallback_provider="groq", llm_fallback_api_key="k")
    assert s.llm_fallback().model == "openai/gpt-oss-120b"
    assert make_settings().llm_fallback() is None


def test_without_provider_extras_keeps_other_messages():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "x"}]
    assert _without_provider_extras(msgs) == msgs


# --- evals: busy provider is "not evaluated", not a failure -----------------------------------


def test_eval_question_is_retried_once_then_marked_not_evaluated(monkeypatch):
    calls, waits = [], []

    async def ask(llm, settings, question):
        calls.append(question)
        raise LLMError("MM-LLM-002", "rate limited", retry_after_s=60.0, retryable=True)

    async def sleep(s):
        waits.append(s)

    monkeypatch.setattr(evals, "ask", ask)
    case = {"id": "cur-1", "category": "current", "question": "q", "critical": True}
    results = asyncio.run(evals.run_cases([case], None, None, sleep=sleep, retry_wait=45))
    assert len(calls) == 2 and waits == [60.0]
    r = results[0]
    assert r.unavailable and r.error
    summary = evals.summarise(results, judged=True)
    assert summary["critical"] == 0 and summary["not_evaluated"] == 1
    assert summary["gate"] is False and summary["complete"] is False
    assert evals._verdict(summary).startswith("INCOMPLETE")
    text = evals.report(results, summary, "gemini", "qwen")
    assert "not evaluated: MM-LLM-002" in text and "INCOMPLETE" in text


def test_eval_second_attempt_can_succeed(monkeypatch):
    attempts = []

    async def run_case(case, llm, settings, judge_llm):
        attempts.append(1)
        if len(attempts) == 1:
            raise LLMError("MM-LLM-002", "HTTP 503", retryable=True)
        return evals.Result(case, answer="fine", model="gpt-oss")

    async def sleep(s):
        pass

    monkeypatch.setattr(evals, "run_case", run_case)
    case = {"id": "jar-1", "category": "jargon", "question": "q"}
    results = asyncio.run(evals.run_cases([case], None, None, sleep=sleep))
    assert results[0].answer == "fine" and not results[0].unavailable
    summary = evals.summarise(results, judged=False)
    assert summary["gate"] and summary["complete"]
    assert "(answered by gpt-oss)" in evals.report(results, summary, "gemini", None)


def test_eval_bad_request_is_not_retried(monkeypatch):
    attempts = []

    async def run_case(case, llm, settings, judge_llm):
        attempts.append(1)
        raise LLMError("MM-LLM-003", "HTTP 400")

    monkeypatch.setattr(evals, "run_case", run_case)
    case = {"id": "adv-1", "category": "adversarial", "question": "q", "critical": True}
    results = asyncio.run(evals.run_cases([case], None, None))
    assert len(attempts) == 1 and results[0].critical
    assert evals._verdict(evals.summarise(results, judged=False)) == "FAIL"
