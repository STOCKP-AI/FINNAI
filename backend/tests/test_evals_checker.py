"""The eval rule checker on real answer fragments from the 9 Oct run (Groq gpt-oss-120b).

Models write typographic characters (non-breaking hyphen U+2011, en dash U+2013 as a minus,
narrow no-break space U+202F) and round numbers; those must not count as invented numbers,
while numbers that really are not in the tool data still must.
"""

import pytest

from app.evals import run as evals

NBH, EN, NNBSP = chr(0x2011), chr(0x2013), chr(0x202F)  # non-breaking hyphen, en dash, narrow space
REGIME = {
    "name": "get_current_regime",
    "arguments": "{}",
    "result": {"as_of": "2026-10-08", "confidence": 0.9972},
}


def ungrounded(answer, tools):
    case = {"id": "x", "category": "t"}
    fails = [f for f in evals.check_rules(case, answer, tools) if f.startswith("numbers")]
    return fails[0] if fails else None


def test_typographic_dates_satisfy_the_date_rule():
    case = {
        "id": "cur-1",
        "category": "current",
        "required": [r"\d{4}-\d{2}-\d{2}|\d{1,2} [A-Z][a-z]{2,8},? \d{4}"],
    }
    answer = f"As of 2026{NBH}10{NBH}08, the model reads the market as Sideways."
    assert evals.check_rules(case, answer, [REGIME]) == []


@pytest.mark.parametrize(
    "text",
    [
        f"the NIFTY{NBH}50 model",
        f"in the COVID{NBH}19 crash",
        f"25th{NBH}percentile and 75 th{NBH}percentile",
        f"the middle 50{NNBSP}% of outcomes",
        f"between the 25{NBH}th and 75-th percentile",
        f"its 52{NBH}week high and its 60{NBH}day high",
        f"as of 08{NBH}Oct{NBH}2026",
    ],
)
def test_names_labels_and_dates_are_not_facts(text):
    assert ungrounded(text, [REGIME]) is None


def test_rounded_numbers_and_dash_minus_are_grounded():
    signals = {"name": "explain_signals", "arguments": "{}", "result": [{"value": -0.102627}]}
    assert ungrounded(f"Drawdown {EN}10.3{NNBSP}% (down)", [signals]) is None
    returns = {"name": "get_forward_returns", "arguments": "{}", "result": {"p25": 13.35, "p75": 27.13}}
    assert ungrounded("from about + 13 % up to + 27 %", [returns]) is None
    assert ungrounded("from about 12 % up to 27 %", [returns]) == "numbers not in tool data: 12"


def test_differences_and_requested_arguments_are_grounded():
    stats = {"name": "get_nifty_stats", "arguments": "{}", "result": {"close": 22231.8, "high_52w": 26328.55}}
    assert ungrounded("≈ 4,096.75 points below the high", [stats]) is None
    history = {"name": "get_regime_history", "arguments": '{"days": 365}', "result": {"points": []}}
    assert ungrounded("Overall picture (365 days)", [history]) is None


def test_invented_numbers_are_still_caught():
    glossary = {"name": "lookup_glossary", "arguments": '{"term": "sharpe"}', "result": {"definition": "..."}}
    assert ungrounded("a Sharpe ratio above 1.5 is good", [glossary]) == "numbers not in tool data: 1.5"
    assert "77.7" in ungrounded("It is 77.7 today.", [REGIME])


def test_judge_is_told_that_correct_refusals_score_high():
    assert "refusal" in evals.JUDGE_PROMPT and "high scores" in evals.JUDGE_PROMPT


def test_analyst_prompt_answers_advice_questions_with_context():
    from app.agent.prompts import ANALYST

    rule = ANALYST.split("2. ", 1)[1].split("3. ", 1)[0]
    assert "get_current_regime" in rule and "get_forward_returns" in rule and "adviser" in rule


def test_plain_and_numbers_with_decimals():
    assert evals.plain(f"a{NBH}b{EN}c{NNBSP}d—e") == "a-b-c d e"
    assert evals.numbers_with_decimals("13 and 13.35 and 4,096.75") == [(13.0, 0), (13.35, 2), (4096.75, 2)]
