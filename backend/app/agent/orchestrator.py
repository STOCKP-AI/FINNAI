"""The analyst's tool loop (Full Project Document 11.2), streamed as events.

    for up to 5 rounds:
        stream the model; forward text as Token events as it arrives
        if it asked for tools: run them (read-only), add the results, go round again
        else: done
    after 5 rounds: one last call without tools (MM-LLM-004)

The caller (api/chat.py, evals) turns the events into SSE or a report. Final.text is exactly
what the user saw streamed (including any short preamble before a tool call).
"""

import json
from dataclasses import dataclass, field

from starlette.concurrency import run_in_threadpool

from app.agent import tools as toolbox
from app.agent.llm import Done, TextDelta, ToolCall
from app.agent.prompts import FINAL_ROUND

MAX_TOOL_ROUNDS = 5


@dataclass
class Token:
    text: str


@dataclass
class ToolStart:
    tool: str
    label: str


@dataclass
class ToolEnd:
    tool: str
    ms: int
    ok: bool


@dataclass
class Final:
    text: str = ""
    tools: list = field(default_factory=list)  # [{"name", "arguments", "status", "result"}]
    tokens_in: int = 0
    tokens_out: int = 0
    warnings: list = field(default_factory=list)
    model: str | None = None


class Orchestrator:
    def __init__(self, llm, settings, max_rounds=MAX_TOOL_ROUNDS):
        self.llm = llm
        self.settings = settings
        self.max_rounds = max_rounds

    async def run(self, system, history, message):
        messages = [*history, {"role": "user", "content": message}]
        final = Final(model=getattr(self.llm, "model", None))
        for _ in range(self.max_rounds):
            calls, round_text = [], ""
            async for ev in self.llm.stream(system, messages, toolbox.SCHEMAS):
                if isinstance(ev, TextDelta):
                    round_text += ev.text
                    final.text += ev.text
                    yield Token(ev.text)
                elif isinstance(ev, ToolCall):
                    calls.append(ev)
                elif isinstance(ev, Done):
                    final.tokens_in += ev.tokens_in or 0
                    final.tokens_out += ev.tokens_out or 0
            if not calls:
                yield final
                return
            messages.append(
                {
                    "role": "assistant",
                    "content": round_text or None,
                    "tool_calls": [c.as_message_part() for c in calls],
                }
            )
            for call in calls:
                yield ToolStart(call.name, toolbox.LABELS.get(call.name, "Working"))
                result, status, ms = await run_in_threadpool(
                    toolbox.run_tool, self.settings, call.name, call.arguments
                )
                if status == "failed" and "MM-TOOL-001" not in final.warnings:
                    final.warnings.append("MM-TOOL-001")
                final.tools.append(
                    {"name": call.name, "arguments": call.arguments, "status": status, "result": result}
                )
                yield ToolEnd(call.name, ms, status == "ok")
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)}
                )

        final.warnings.append("MM-LLM-004")
        messages.append({"role": "user", "content": FINAL_ROUND})
        async for ev in self.llm.stream(system, messages, None):
            if isinstance(ev, TextDelta):
                final.text += ev.text
                yield Token(ev.text)
            elif isinstance(ev, Done):
                final.tokens_in += ev.tokens_in or 0
                final.tokens_out += ev.tokens_out or 0
        yield final
