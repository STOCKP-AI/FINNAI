"""Provider-neutral LLM adapter (Prototype Build Plan v2.1 section 8.3).

One interface, several providers. Every client turns a provider's stream into three neutral
events: TextDelta (part of the answer), ToolCall (the model wants data) and Done (end of a
round, with token counts when the provider reports them).

    OpenAICompatClient  Gemini (free tier), Groq, GitHub Models - all speak the OpenAI API
    MockClient          canned, rule-based answers (tests, demo safety net; app/agent/mock.py)
    AnthropicClient     Phase 7 (full product)

Messages use the OpenAI chat format. Gemini 3 returns a "thought signature" with each function
call (tool_calls[].extra_content.google.thought_signature) and rejects the next request if it
is not sent back unchanged, so ToolCall keeps `extra` and the orchestrator returns it.
"""

from dataclasses import dataclass, field


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

    def __str__(self):
        return f"{self.code}: {self.message}"


class OpenAICompatClient:
    """Any OpenAI-compatible chat completions endpoint, streamed."""

    def __init__(self, config, client=None, max_tokens=None):
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                base_url=config.base_url, api_key=config.api_key, timeout=config.timeout_s, max_retries=1
            )
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
            raise LLMError("MM-LLM-001", "timeout") from exc
        except openai.RateLimitError as exc:
            raise LLMError("MM-LLM-002", "rate limited") from exc
        except openai.APIStatusError as exc:
            code = "MM-LLM-002" if exc.status_code in (429, 503, 529) else "MM-LLM-003"
            raise LLMError(code, f"HTTP {exc.status_code}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("MM-LLM-003", "connection failed") from exc


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


def make_client(config):
    """LLM client for a resolved LLMConfig (app/core/config.py)."""
    if config.provider == "mock":
        from app.agent.mock import MockClient

        return MockClient()
    return OpenAICompatClient(config)
