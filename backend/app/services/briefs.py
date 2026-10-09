"""The dashboard's daily brief: the facts it may use, a template version, and the checks an
AI-written version must pass (SOA 5.7): every number must appear in the facts (within 0.1),
no advice words, 30-90 words. Otherwise the template is used (MM-LLM-005)."""

import re

from app.services import market

BANNED = re.compile(
    r"\b(buy|sell|target|guarantee[ds]?|recommend\w*|should invest|stop[- ]loss|sure shot)\b", re.IGNORECASE
)
NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2} [A-Z][a-z]{2,8},? \d{4}\b")
NAMES = re.compile(r"NIFTY\s*50|\b\d+[- ](?:day|week|month|year)s?\b", re.IGNORECASE)  # not facts


def brief_facts(rows):
    """Everything the brief may mention, from the regime series (latest row last)."""
    last = rows[-1]
    labels = [r["confirmed_label"] for r in rows]
    n = market.days_in_regime(labels)
    prev = rows[-2]["confirmed_label"] if len(rows) > 1 else last["confirmed_label"]
    stats = market.nifty_stats(rows)
    signals = market.describe_signals(last["signals"])
    return {
        "date": last["date"].isoformat(),
        "regime": last["confirmed_label"],
        "previous_regime": prev,
        "days_in_regime": n,
        "confidence_pct": round(float(last["confidence"]) * 100, 1),
        "nifty_close": stats["close"],
        "nifty_change_pct": stats["change_pct"],
        "from_52w_high_pct": stats["from_high_pct"],
        "ytd_pct": stats["ytd_pct"],
        "signals": [s["text"] for s in signals],
    }


def lower_first(text):
    """'Daily swings ...' -> 'daily swings ...', but keep 'NIFTY ...' and 'VIX ...' as they are."""
    first = text.split(" ", 1)[0]
    return text if first.isupper() else text[:1].lower() + text[1:]


def template_brief(f):
    change = f"{f['nifty_change_pct']:+.2f}%" if f["nifty_change_pct"] is not None else "no change data"
    days = f"{f['days_in_regime']} trading day" + ("s" if f["days_in_regime"] != 1 else "")
    signals = "; ".join(lower_first(s) for s in f["signals"][:2]) or "no clear signal"
    brief = (
        f"NIFTY 50 closed at {f['nifty_close']:,.2f} on {f['date']} ({change}). "
        f"MarketMood's model reads the market as {f['regime']}, for {days} now, "
        f"with {f['confidence_pct']:.1f}% confidence. Main signals: {signals}."
    )
    if f["previous_regime"] != f["regime"]:
        changed = f"The regime changed from {f['previous_regime']} to {f['regime']}."
    else:
        changed = "No regime change since the previous trading day."
    return brief, changed


def _numbers(text):
    text = NAMES.sub(" ", DATE.sub(" ", text))
    out = []
    for m in NUMBER.finditer(text):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:  # pragma: no cover - regex only matches numbers
            continue
    return out


def _fact_numbers(facts):
    nums = []
    for k, v in facts.items():
        if isinstance(v, int | float) and not isinstance(v, bool):
            nums += [float(v), abs(float(v))]
        if k == "date":
            nums += [float(x) for x in v.split("-")]
    return nums


def check_brief(text, what_changed, facts):
    """Return a list of problems; empty means the AI text may be published."""
    problems = []
    words = len(text.split())
    if not 30 <= words <= 90:
        problems.append(f"{words} words (allowed 30-90)")
    combined = f"{text} {what_changed or ''}"
    if BANNED.search(combined):
        problems.append(f"banned phrase: {BANNED.search(combined).group()!r}")
    allowed = _fact_numbers(facts)
    for n in _numbers(combined):
        if n in (1, 2, 3) or any(abs(n - a) <= 0.1 for a in allowed):
            continue
        problems.append(f"number not in the facts: {n:g}")
    return problems
