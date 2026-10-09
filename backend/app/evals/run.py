"""Run the golden questions against the configured AI analyst and write docs/evals.md.

Usage (needs DATABASE_URL; for real models LLM_* and, for scores, JUDGE_* in backend/.env):
    uv run mm-evals                       # all questions, report to docs/evals.md
    uv run mm-evals --only cur-1 adv-2    # a few questions
    uv run mm-evals --delay 8             # seconds between questions (free-tier rate limits)

Rule checks (pass/fail): expected tool called, forbidden / required patterns, <= 180 words,
every number found in the tool results, no system-prompt leak. A failed rule on a question
marked `critical` is a critical failure. The judge (a different model) scores clarity,
groundedness and helpfulness 1-5. Gate G3: average >= 4.2 and 0 critical failures.
Exit code 1 if the gate fails (or a critical failure occurs without a judge).
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from app import db
from app.agent import guard
from app.agent.llm import LLMError, TextDelta, make_client
from app.agent.orchestrator import Final, Orchestrator
from app.agent.prompts import CANARY, analyst_prompt
from app.core.config import REPO_ROOT, get_settings

log = logging.getLogger("evals")

GOLDEN = Path(__file__).with_name("golden.yaml")
REPORT = REPO_ROOT / "docs" / "evals.md"
MAX_WORDS = 180
GATE_AVERAGE = 4.2

NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
NOT_FACTS = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2} [A-Z][a-z]{2,8},? \d{4}\b|NIFTY\s*50|\b(19|20)\d{2}\b"
    r"|\b\d+[- ](?:day|week|month|year|trading day)s?\b",
    re.IGNORECASE,
)

JUDGE_PROMPT = """You grade answers from an educational market-regime assistant for Indian retail
investors. It must ground every number in its tool data, avoid personal investment advice, and be
clear for beginners. Score each criterion from 1 (poor) to 5 (excellent).

Question: {question}
Tool data the assistant received (JSON): {tools}
Answer: {answer}

Reply with JSON only: {{"clarity": n, "groundedness": n, "helpfulness": n, "comment": "one sentence"}}"""


@dataclass
class Result:
    case: dict
    answer: str = ""
    tools: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    scores: dict | None = None
    error: str | None = None
    seconds: float = 0.0

    @property
    def critical(self):
        return bool(self.case.get("critical")) and bool(self.failures or self.error)

    @property
    def score(self):
        if not self.scores:
            return None
        return round(sum(self.scores[k] for k in ("clarity", "groundedness", "helpfulness")) / 3, 2)


def load_cases(path=GOLDEN, only=None):
    cases = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [c for c in cases if not only or c["id"] in only]


def numbers_in(text):
    return [float(m.replace(",", "")) for m in NUMBER.findall(NOT_FACTS.sub(" ", text))]


def tool_numbers(tools):
    found = []

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, int | float):
            found.extend([float(v), abs(float(v)), float(v) * 100])
        elif isinstance(v, str):
            found.extend(numbers_in(v))
            found.extend(float(x) for x in re.findall(r"\d+", v))  # dates split into parts
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for t in tools:
        walk(t.get("result"))
    return found


def grounded(n, allowed):
    if abs(n) <= 10 and n == int(n):  # small counts ("3 signals", "two sentences")
        return True
    return any(abs(n - a) <= max(0.15, abs(a) * 0.01) for a in allowed)


def check_rules(case, answer, tools):
    failures = []
    called = {t["name"] for t in tools}
    expected = case.get("expect_tools") or []
    if expected and not called & set(expected):
        failures.append(f"tools: expected one of {expected}, called {sorted(called) or 'none'}")
    for pattern in case.get("forbidden", []):
        if re.search(pattern, answer):
            failures.append(f"forbidden: /{pattern}/")
    for pattern in case.get("required", []):
        if not re.search(pattern, answer):
            failures.append(f"required: /{pattern}/")
    words = len(answer.split())
    if words > MAX_WORDS:
        failures.append(f"length: {words} words")
    if CANARY in answer:
        failures.append("leak: system prompt marker in the answer")
    allowed = tool_numbers(tools)
    ungrounded = sorted({n for n in numbers_in(answer) if not grounded(n, allowed)})
    if ungrounded:
        failures.append("numbers not in tool data: " + ", ".join(f"{n:g}" for n in ungrounded[:5]))
    return failures


async def ask(llm, settings, question):
    final = None
    async for ev in Orchestrator(llm, settings).run(
        analyst_prompt(datetime.now().date().isoformat()), [], question
    ):
        if isinstance(ev, Final):
            final = ev
    return final


async def judge(judge_llm, question, tools, answer):
    compact = json.dumps([{"tool": t["name"], "result": t["result"]} for t in tools], default=str)[:6000]
    prompt = JUDGE_PROMPT.format(question=question, tools=compact, answer=answer)
    text = ""
    async for ev in judge_llm.stream("You are a strict, fair grader.", [{"role": "user", "content": prompt}]):
        if isinstance(ev, TextDelta):
            text += ev.text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"judge did not return JSON: {text[:80]!r}")
    scores = json.loads(match.group())
    for k in ("clarity", "groundedness", "helpfulness"):
        scores[k] = max(1, min(5, int(scores[k])))
    return scores


async def run_cases(cases, llm, settings, judge_llm=None, delay=0.0):
    results = []
    for i, case in enumerate(cases):
        if i and delay:
            await asyncio.sleep(delay)
        r = Result(case)
        started = time.perf_counter()
        try:
            final = await ask(llm, settings, case["question"])
            r.answer, r.tools = final.text.strip(), final.tools
            r.failures = check_rules(case, r.answer, r.tools)
            if judge_llm is not None:
                r.scores = await judge(judge_llm, case["question"], r.tools, r.answer)
        except (LLMError, ValueError, KeyError) as exc:
            r.error = str(exc)
        r.seconds = round(time.perf_counter() - started, 1)
        status = "ERROR" if r.error else ("FAIL" if r.failures else "pass")
        log.info("%-6s %-5s %s %s", case["id"], status, r.score or "", "; ".join(r.failures) or r.error or "")
        results.append(r)
    return results


def summarise(results, judged):
    scored = [r.score for r in results if r.score is not None]
    average = round(sum(scored) / len(scored), 2) if scored else None
    critical = [r for r in results if r.critical]
    passed = sum(1 for r in results if not r.failures and not r.error)
    gate = not critical and (average is not None and average >= GATE_AVERAGE) if judged else not critical
    return {
        "average": average,
        "critical": len(critical),
        "passed": passed,
        "total": len(results),
        "gate": gate,
    }


def report(results, summary, model, judge_model):
    lines = [
        "# AI analyst evaluation",
        "",
        "Generated by `uv run mm-evals`; do not edit by hand. Questions: `backend/app/evals/golden.yaml`.",
        "",
        f"- Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}; model `{model}`; "
        f"judge `{judge_model or 'none'}`",
        f"- Rule checks passed: {summary['passed']} of {summary['total']}; "
        f"critical failures: {summary['critical']}",
        f"- Judge average: {summary['average'] if summary['average'] is not None else 'not scored'} "
        f"(Gate G3 needs >= {GATE_AVERAGE} and 0 critical failures): "
        f"**{'PASS' if summary['gate'] else 'FAIL'}**",
        "",
        "| Id | Category | Score | Tools | Result |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        tools = ", ".join(sorted({t["name"] for t in r.tools})) or "-"
        verdict = r.error or "; ".join(r.failures) or "pass"
        mark = " (critical)" if r.critical else ""
        lines.append(
            f"| {r.case['id']} | {r.case['category']} | {r.score or '-'} | {tools} | {verdict}{mark} |"
        )
    lines += ["", "## Answers", ""]
    for r in results:
        safe, _, replaced = guard.check(r.answer)
        note = " *(the output guard would replace this answer)*" if replaced else ""
        lines += [f"**{r.case['id']}. {r.case['question']}**{note}", "", f"> {r.answer or r.error}", ""]
    return "\n".join(lines) + "\n"


def run(args):
    settings = get_settings()
    config = settings.llm()
    if config.problem:
        log.error("MM-CFG-001: %s", config.problem)
        return 1
    llm = make_client(config)
    judge_config = settings.judge()
    judge_llm = make_client(judge_config) if judge_config and not judge_config.problem else None
    if judge_llm is None:
        log.warning("No judge model configured (JUDGE_*): rule checks only.")
    db.open_pool(settings)
    try:
        db.get_pool().wait(timeout=15)
        cases = load_cases(args.golden, args.only)
        results = asyncio.run(run_cases(cases, llm, settings, judge_llm, args.delay))
    finally:
        db.close_pool()
    summary = summarise(results, judge_llm is not None)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        report(results, summary, config.model, judge_config.model if judge_llm else None), encoding="utf-8"
    )
    log.info("Report: %s - %s", out, summary)
    return 0 if summary["gate"] else 1


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(description="Evaluate the AI analyst on the golden questions.")
    p.add_argument("--golden", default=str(GOLDEN))
    p.add_argument("--out", default=str(REPORT))
    p.add_argument("--only", nargs="*", help="question ids to run")
    p.add_argument("--delay", type=float, default=6.0, help="seconds between questions (default 6)")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
