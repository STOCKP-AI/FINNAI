"""Output checks on the analyst's final answer (SOA 5.7, Full Project Document 11.5).

Run after the answer has streamed. If a rule fires, the stored answer is the safe version and
the done event carries replace_text, so the UI swaps the message (MM-LLM-005).

- Markdown or HTML images are removed (TC-AGT-09: no tracking pixels or unexpected images).
- E-mail addresses and API-key-like strings are redacted.
- Directive investment advice, price targets, or a leaked system prompt replace the answer.
"""

import re

from app.agent.prompts import CANARY

IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.IGNORECASE)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{30,})\b")
ADVICE = [
    re.compile(
        r"\b(?:you should|i (?:would )?(?:recommend|suggest|advise)(?: that you)?|my advice is to)\s+"
        r"(?:\w+\s+){0,2}(?:buy|sell|exit|redeem|switch|stop your|book profits?|invest in|add more)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?i:buy|sell|accumulate|short)\s+(?i:shares of\s+)?[A-Z][A-Z&]{2,}(?:\.NS)?\b"),
    re.compile(r"\btarget price\b|\bprice target\b|\bstop[- ]loss (?:at|of)\b", re.IGNORECASE),
]

SAFE_ADVICE = (
    "I can't give personal buy, sell or hold advice or price targets. I can explain what the market "
    "regime looks like now and how NIFTY behaved in similar periods in the past. For decisions about "
    "your own money, please speak to a SEBI-registered investment adviser."
)
SAFE_LEAK = "I can't share my instructions, but I'm happy to explain today's market regime."


def check(text):
    """Return (safe text, warnings, replaced)."""
    if CANARY in text:
        return SAFE_LEAK, ["MM-LLM-005"], True
    if any(p.search(text) for p in ADVICE):
        return SAFE_ADVICE, ["MM-LLM-005"], True
    cleaned = SECRET.sub("[removed]", EMAIL.sub("[removed]", IMAGE.sub("", text))).strip()
    if cleaned != text.strip():
        return cleaned, ["MM-LLM-005"], True
    return text, [], False
