"""Mock LLM: rule-based answers built from real tool results (LLM_PROVIDER=mock).

It behaves like a small, careful model: it picks tools from keywords, calls them through the
real tool loop, then writes a templated answer from the results. Used by the tests, by the
frontend team without an API key, and as the demo safety net. It never invents numbers.
"""

import json
import re
from datetime import datetime

from app.agent.llm import Done, TextDelta, ToolCall
from app.agent.prompts import FINAL_ROUND
from app.services.briefs import lower_first

GLOSSARY_WORDS = [
    "india vix", "vix", "drawdown", "sip", "volatility", "sharpe", "bollinger", "skew", "autocorrelation",
    "index fund", "mutual fund", "etf", "cagr", "correction", "bear market", "bull market", "diversification",
    "asset allocation", "rebalancing", "risk tolerance", "hidden markov", "hmm", "sebi", "fii", "dii",
    "moving average", "confidence", "regime",
]  # fmt: skip

INTENTS = [
    ("injection", r"ignore (all |your |the |previous )?(instructions|rules)|system prompt"
     r"|your (instructions|prompt)"
     r"|developer mode|jailbreak|pretend (you|to be)"),
    ("stock_pick", r"\b(which|what|best|top)\b.{0,20}\b(stocks?|shares?|compan(y|ies)|multibagger)\b"
     r"|stock tips?"),
    ("greeting", r"^\s*(hi|hello|hey|namaste|good (morning|evening))\b[\s!.]*$"),
    ("advice", r"\bshould i\b|\b(sell|redeem|stop|exit) my\b|good time to (buy|sell|invest)|invest now\b"),
    ("why", r"\bwhy\b|\bsignals?\b|\breasons?\b|\bdriv(e|es|ing)\b"),
    ("after", r"\bafter\b.*\b(crisis|bull|sideways|regime)|\bforward returns?|base rates?"
     r"|what happened to nifty"),
    ("history", r"\bhistor(y|ical)\b|\bchanged?\b|\bthis year\b|\blast year\b|\bepisodes?\b|\btimeline\b"
     r"|\bpast\b|\bwhen was\b|\blast (crisis|bull|sideways)\b|\bcovid\b|\bcrash\b|\b(19|20)\d{2}\b"),
    ("glossary", r"\bwhat (is|are|does)\b|\bmeaning\b|\bdefine\b|\bdefinition\b|\bstand for\b|\bexplain\b"),
    ("nifty", r"\bnifty\b.*\b(level|close|high|low|ytd|today|stats?)\b|\b52[- ]week\b"),
]  # fmt: skip

REGIME_WORDS = {"crisis": "Crisis", "bull": "Bull", "sideways": "Sideways"}


def classify(text):
    t = text.lower()
    for name, pattern in INTENTS:
        if re.search(pattern, t):
            if name == "glossary" and re.search(r"\b(regime|market) (today|now)\b|current regime", t):
                return "today"
            if name == "glossary" and not _term(t):
                continue
            return name
    return "today"


def _term(t):
    for word in GLOSSARY_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", t):
            return word
    return None


def _regime_in(t):
    for word, label in REGIME_WORDS.items():
        if word in t:
            return label
    return None


def _history_days(t):
    """Calendar days back to cover a year named in the question (e.g. 2020), else one year."""
    years = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", t)]
    if years:
        return min(3650, max(365, (datetime.now().year - min(years) + 1) * 366))
    return 365


def plan(intent, text, results):
    """Next tool call (name, args) for this intent given the results so far, or None."""
    t = text.lower()
    current = results.get("get_current_regime", {}).get("regime")
    steps = {
        "today": [("get_current_regime", {})],
        "why": [("get_current_regime", {}), ("explain_signals", {})],
        "advice": [
            ("get_current_regime", {}),
            ("get_forward_returns", {"regime": current or "Sideways", "horizon_days": 252}),
        ],
        "after": [("get_forward_returns", {"regime": _regime_in(t) or "Crisis", "horizon_days": 252})],
        "history": [("get_historical_episodes", {"regime": _regime_in(t), "limit": 3})]
        if _regime_in(t)
        else [("get_regime_history", {"days": _history_days(t)})],
        "glossary": [("lookup_glossary", {"term": _term(t) or t[:60]})],
        "nifty": [("get_nifty_stats", {})],
    }.get(intent, [])
    for name, args in steps:
        if name not in results:
            if name == "get_forward_returns" and intent == "advice" and current is None:
                return None
            return name, args
    return None


def compose(intent, results):
    cur = results.get("get_current_regime")
    if intent == "injection":
        return "I can't share or change my instructions, but I'm happy to explain today's market regime."
    if intent == "stock_pick":
        return (
            "I can't recommend stocks or tell you what to buy. I can show you what the market regime "
            "looks like now and how NIFTY behaved in similar periods. For personal decisions, please "
            "speak to a SEBI-registered investment adviser."
        )
    if intent == "greeting":
        return (
            "Hello! I explain what MarketMood's regime model sees in the NIFTY 50 market: today's "
            "regime, why, and what happened in similar periods. What would you like to know?"
        )
    if any(r.get("error", "").startswith("This data is unavailable") for r in results.values()):
        return (
            "Sorry, that data is unavailable right now, so I can't answer with numbers. "
            "Please try again later."
        )
    parts = []
    if cur:
        stale = " Note: this is not today's data yet." if cur.get("is_stale") else ""
        parts.append(
            f"As of {cur['as_of']}, the model reads the market as {cur['regime']} "
            f"(confidence {cur['confidence_pct']}%), for {cur['days_in_regime']} trading days now.{stale}"
        )
    sig = results.get("explain_signals")
    if sig:
        texts = [f"{lower_first(s['text'])} ({s['name']})" for s in sig["signals"][:3]]
        parts.append("The main signals: " + "; ".join(texts) + ".")
    fwd = results.get("get_forward_returns")
    if fwd and fwd.get("n"):
        parts.append(
            f"In the past, {fwd['horizon_days']} trading days after NIFTY entered a {fwd['regime']} regime, "
            f"its median return was {fwd['median_pct']}% "
            f"(middle half {fwd['p25_pct']}% to {fwd['p75_pct']}%, "
            f"{fwd['n']} episodes). That is history, not a forecast."
        )
    elif fwd:
        parts.append(f"There are no completed past {fwd['regime']} episodes to compare with yet.")
    hist = results.get("get_regime_history")
    if hist:
        days = ", ".join(f"{k} {v}" for k, v in hist["trading_days_by_regime"].items() if v)
        parts.append(
            f"From {hist['from']} to {hist['to']}, trading days by regime: {days}; "
            f"{len(hist['regime_changes'])} regime changes."
        )
    eps = results.get("get_historical_episodes")
    if eps and eps["episodes"]:
        e = eps["episodes"][0]
        parts.append(
            f"The most recent {eps['regime']} episode ran from {e['start']} to {e['end']} "
            f"({e['trading_days']} trading days); NIFTY changed {e['nifty_change_pct']}% with a worst "
            f"drawdown of {e['max_drawdown_pct']}%."
        )
    gl = results.get("lookup_glossary")
    if gl:
        parts.append(gl.get("definition", "I don't have that term in my glossary yet."))
    st = results.get("get_nifty_stats")
    if st:
        parts.append(
            f"As of {st['as_of']}, NIFTY 50 closed at {st['close']:,} ({st['change_pct']}% on the day), "
            f"{st['from_high_pct']}% from its 52-week high of {st['high_52w']:,}."
        )
    if intent == "advice":
        parts.append(
            "I can't tell you what to do with your own money; a SEBI-registered investment adviser can "
            "help with that."
        )
    return " ".join(parts) or "I don't have data for that yet."


class MockClient:
    provider = "mock"
    model = "mock"

    async def stream(self, system, messages, tools=None):
        user_idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
        text = messages[user_idx]["content"]
        if text == FINAL_ROUND:
            user_idx = max(i for i, m in enumerate(messages[:user_idx]) if m["role"] == "user")
            text = messages[user_idx]["content"]
        names, results = {}, {}
        for m in messages[user_idx + 1 :]:
            for tc in m.get("tool_calls") or []:
                names[tc["id"]] = tc["function"]["name"]
            if m["role"] == "tool":
                results[names.get(m["tool_call_id"], "?")] = json.loads(m["content"])
        intent = classify(text)
        step = plan(intent, text, results) if tools else None
        if step:
            name, args = step
            yield ToolCall(f"mock_{len(results)}_{name}", name, json.dumps(args))
            yield Done("tool_calls", 0, 0)
            return
        answer = compose(intent, results)
        for word in re.findall(r"\S+\s*", answer):
            yield TextDelta(word)
        yield Done("stop", 0, len(answer.split()))
