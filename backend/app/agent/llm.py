"""Provider-neutral LLM adapter (Prototype Build Plan v2.1 section 8.3).

One interface, several providers. Every client turns a provider's stream into three neutral
events: TextDelta (part of the answer), ToolCall (the model wants data) and Done (end of a
round, with token counts when the provider reports them).

    OpenAICompatClient  Gemini (free tier), Groq, GitHub Models - all speak the OpenAI API
    ResilientClient     wraps them: short retries when the provider is busy (HTTP 429/503),
                        then an optional fallback model (LLM_FALLBACK_*, e.g. Gemini -> Groq)
    MockClient          canned, rule-based answers (tests, demo safety net; app/agent/mock.py)
    AnthropicClient     Phase 7 (full product)

Messages use the OpenAI chat format. Gemini 3 returns a "thought signature" with each function
call (tool_calls[].extra_content.google.thought_signature) and rejects the next request if it
is not sent back unchanged, so ToolCall keeps `extra` and the orchestrator returns it.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("llm")

RETRY_WAITS_S = (2.0, 6.0)  # waits before the 2nd and 3rd attempt on a busy provider
MAX_WAIT_S = 10.0  # a provider asking for a longer pause is skipped (fallback, or the error)
_RETRY_DELAY = re.compile(r"retry(?:[ _-]?delay|[ _-]?after)?[\"':\s]*(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str
    extra: dict | None = None  # provider fields to send back unchanged (Gemini thought signature)

    def as_message_part(self):
        part = {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }
        if self.extra:
            part["extra_content"] = self.extra
        return part


@dataclass
class Done:
    finish_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


@dataclass
class LLMError(Exception):
    code: str  # MM-LLM-001 timeout, MM-LLM-002 rate limit / overloaded, MM-LLM-003 other error
    message: str = ""
    retry_after_s: float | None = field(default=None)
    retryable: bool = False  # worth trying again (busy, timeout, connection) - not a bad request

    def __str__(self):
        return f"{self.code}: {self.message}"


class OpenAICompatClient:
    """Any OpenAI-compatible chat completions endpoint, streamed."""

    def __init__(self, config, client=None, max_tokens=None):
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                base_url=config.base_url, api_key=config.api_key, timeout=config.timeout_s, max_retries=0
            )  # retries are done by ResilientClient, with waits that suit free-tier limits
        self.client = client
        self.model = config.model
        self.provider = config.provider
        self.max_tokens = max_tokens

    async def stream(self, system, messages, tools=None):
        import openai

        kwargs = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens
        try:
            response = await self.client.chat.completions.create(**kwargs)
            calls, finish, usage = {}, None, None
            async for chunk in response:
                usage = getattr(chunk, "usage", None) or usage
                for choice in chunk.choices or []:
                    delta = choice.delta
                    if delta is not None and delta.content:
                        yield TextDelta(delta.content)
                    for tc in (delta.tool_calls if delta is not None else None) or []:
                        _merge_tool_delta(calls, tc)
                    if choice.finish_reason:
                        finish = choice.finish_reason
            for i in sorted(calls):
                c = calls[i]
                yield ToolCall(c["id"] or f"call_{i}", c["name"], c["arguments"] or "{}", c["extra"])
            yield Done(
                finish,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
        except openai.APITimeoutError as exc:
            raise LLMError("MM-LLM-001", "timeout", retryable=True) from exc
        except openai.APIStatusError as exc:
            busy = exc.status_code in (429, 500, 502, 503, 504, 529)
            what = "rate limited" if exc.status_code == 429 else f"HTTP {exc.status_code}"
            raise LLMError(
                "MM-LLM-002" if busy else "MM-LLM-003",
                f"{self.provider}: {what}{_detail(exc)}",
                retry_after_s=_retry_after(exc),
                retryable=busy,
            ) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("MM-LLM-003", f"{self.provider}: connection failed", retryable=True) from exc


def _retry_after(exc):
    """Seconds the provider asks us to wait (Retry-After header, or Gemini's retryDelay)."""
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    try:
        if header is not None:
            return float(header)
    except ValueError:
        pass
    match = _RETRY_DELAY.search(str(getattr(exc, "body", "") or "") + " " + str(exc))
    return float(match.group(1)) if match else None


def _detail(exc):
    """A short, key-free hint from the provider (e.g. which quota ran out) for the logs."""
    body = getattr(exc, "body", None)
    text = body.get("message") if isinstance(body, dict) else None
    text = text or (str(body) if body else "")
    text = " ".join(text.split())[:160]
    return f" ({text})" if text else ""


class ResilientClient:
    """A primary model with short retries, then an optional fallback model.

    Only a call that has not produced any output yet is retried, so an answer is never
    repeated. Once the fallback has answered, this client keeps using it (one request or one
    eval run), so a conversation never mixes providers mid-way. Gemini's thought signatures
    are removed from the history sent to the fallback, which does not know them.
    """

    def __init__(self, primary, fallback=None, waits=RETRY_WAITS_S, max_wait=MAX_WAIT_S, sleep=asyncio.sleep):
        self.primary, self.fallback = primary, fallback
        self.active = primary
        self.waits, self.max_wait, self.sleep = tuple(waits), max_wait, sleep

    @property
    def model(self):
        return self.active.model

    @property
    def provider(self):
        return self.active.provider

    async def stream(self, system, messages, tools=None):
        order = [self.active] if self.active is not self.primary else [self.primary, self.fallback]
        last = None
        for client in (c for c in order if c is not None):
            msgs = messages if client is self.primary else _without_provider_extras(messages)
            for attempt in range(len(self.waits) + 1):
                produced = False
                try:
                    async for ev in client.stream(system, msgs, tools):
                        produced = True
                        yield ev
                    self.active = client
                    return
                except LLMError as exc:
                    if produced or not exc.retryable:
                        raise
                    last = exc
                    wait = exc.retry_after_s if exc.retry_after_s is not None else None
                    if attempt == len(self.waits) or (wait is not None and wait > self.max_wait):
                        break
                    wait = self.waits[attempt] if wait is None else max(wait, 0.5)
                    log.info("%s busy (%s); retrying in %.0f s", client.model, exc, wait)
                    await self.sleep(wait)
            if client is self.primary and self.fallback is not None:
                log.warning("%s unavailable (%s); answering with %s", client.model, last, self.fallback.model)
        raise last


def _without_provider_extras(messages):
    """Copy of the history without provider-specific fields (Gemini thought signatures)."""
    out = []
    for m in messages:
        if m.get("tool_calls"):
            m = {
                **m,
                "tool_calls": [
                    {k: v for k, v in tc.items() if k != "extra_content"} for tc in m["tool_calls"]
                ],
            }
        out.append(m)
    return out


def _merge_tool_delta(calls, tc):
    """Tool calls arrive in pieces keyed by index (some providers omit the index)."""
    index = tc.index
    if index is None:
        index = len(calls) if (tc.id or not calls) else max(calls)
    slot = calls.setdefault(index, {"id": None, "name": "", "arguments": "", "extra": None})
    if tc.id:
        slot["id"] = tc.id
    fn = tc.function
    if fn is not None:
        if fn.name:
            slot["name"] = fn.name if not slot["name"] or slot["name"] == fn.name else slot["name"] + fn.name
        if fn.arguments:
            slot["arguments"] += fn.arguments
    extra = (getattr(tc, "model_extra", None) or {}).get("extra_content")
    if extra:
        slot["extra"] = extra


def make_client(config, fallback=None):
    """LLM client for a resolved LLMConfig (app/core/config.py), with retries and fallback."""
    if config.provider == "mock":
        from app.agent.mock import MockClient

        return MockClient()
    usable = fallback is not None and fallback.provider != "mock" and fallback.problem is None
    return ResilientClient(OpenAICompatClient(config), OpenAICompatClient(fallback) if usable else None)
