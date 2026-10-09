"""Pure calculations: staleness, days in regime, downsampling, episodes, base rates, briefs, guard."""

from datetime import date, datetime

import pytest

from app.agent import guard
from app.agent.prompts import CANARY
from app.core.errors import ApiError
from app.services import briefs, market

IST = market.IST


def rows_from(labels, closes=None, start=date(2024, 1, 1)):
    closes = closes or [100 + i for i in range(len(labels))]
    out, d = [], start
    for lab, c in zip(labels, closes, strict=True):
        out.append({"date": d, "confirmed_label": lab, "close": c})
        d = date.fromordinal(d.toordinal() + 1)
    return out


def test_last_trading_day_and_staleness():
    """TC-API-02 logic: stale when the latest regime is older than the last closed session."""
    tue_evening = datetime(2026, 10, 6, 17, 0, tzinfo=IST)
    tue_morning = datetime(2026, 10, 6, 10, 0, tzinfo=IST)
    sunday = datetime(2026, 10, 4, 12, 0, tzinfo=IST)
    assert market.last_trading_day(tue_evening) == date(2026, 10, 6)
    assert market.last_trading_day(tue_morning) == date(2026, 10, 5)
    assert market.last_trading_day(sunday) == date(2026, 10, 2)
    assert market.last_trading_day(sunday, holidays=[date(2026, 10, 2)]) == date(2026, 10, 1)
    assert market.is_stale(date(2026, 10, 5), tue_evening)
    assert not market.is_stale(date(2026, 10, 6), tue_evening)
    assert not market.is_stale(date(2026, 10, 5), tue_morning)


def test_days_in_regime_and_downsample():
    assert market.days_in_regime(["Bull", "Crisis", "Crisis", "Crisis"]) == 3
    assert market.days_in_regime([]) == 0
    rows = list(range(2000))
    small = market.downsample(rows, 500)
    assert len(small) <= 500 and small[0] == 0 and small[-1] == 1999 and small == sorted(small)
    assert market.downsample(rows[:10], 500) == rows[:10]


def test_episodes_and_drawdown():
    labels = ["Bull"] * 3 + ["Crisis"] * 3 + ["Bull"] * 2
    closes = [100, 110, 120, 120, 90, 108, 110, 115]
    eps = market.episodes(rows_from(labels, closes))
    assert [(e["regime"], e["days"]) for e in eps] == [("Bull", 3), ("Crisis", 3), ("Bull", 2)]
    crisis = eps[1]
    assert crisis["nifty_change_pct"] == -10.0 and crisis["max_drawdown_pct"] == -25.0
    assert eps[-1]["ongoing"] and not eps[0]["ongoing"]


def test_forward_returns_skip_the_first_run():
    labels = ["Crisis"] * 3 + ["Bull"] * 3 + ["Crisis"] * 2 + ["Bull"] * 4
    closes = [100.0 + i for i in range(len(labels))]
    out = market.forward_returns(rows_from(labels, closes), "Crisis", 2)
    assert out["n"] == 1 and out["small_sample"]  # the run at index 0 is not an observed entry
    assert out["median_pct"] == round((closes[8] / closes[6] - 1) * 100, 2)
    assert market.forward_returns(rows_from(labels, closes), "Sideways", 2)["n"] == 0
    many = ["Bull", "Crisis"] * 10 + ["Bull"] * 5
    out = market.forward_returns(rows_from(many), "Crisis", 3)
    assert (
        out["n"] == 10 and not out["small_sample"] and out["p25_pct"] <= out["median_pct"] <= out["p75_pct"]
    )


def test_nifty_stats():
    labels = ["Bull"] * 400
    closes = [100.0 + i for i in range(399)] + [450.0]
    rows = rows_from(labels, closes, start=date(2025, 1, 1))
    s = market.nifty_stats(rows)
    assert (
        s["close"] == 450.0
        and s["high_52w"] == 498.0
        and s["from_high_pct"] == round((450 / 498 - 1) * 100, 2)
    )
    assert s["ytd_pct"] == round((450 / closes[364] - 1) * 100, 2)  # last close of 2025


def test_signals_text_and_percentiles():
    sig = [{"feature": "vix_level", "value": 30, "direction": "up", "contribution": 1.0}]
    out = market.describe_signals(sig, {"vix_level": 95.0})
    assert out[0]["name"] == "India VIX" and "above" in out[0]["text"] and out[0]["percentile"] == 95.0
    unknown = market.describe_signals([{"feature": "x", "value": 1, "direction": "down", "contribution": 0}])
    assert unknown[0]["text"] == "Below usual"
    table = [{"date": date(2024, 1, d), **{f: float(d) for f in market.FEATURE_TEXT}} for d in range(1, 11)]
    assert market.feature_percentiles(table, date(2024, 1, 5))["vix_level"] == 50.0
    assert market.feature_percentiles(table, date(2023, 1, 1)) == {}
    assert market.feature_percentiles([], date(2024, 1, 1)) == {}
    with pytest.raises(ApiError):
        market.parse_date("yesterday")


FACTS = {
    "date": "2026-10-08",
    "regime": "Sideways",
    "previous_regime": "Sideways",
    "days_in_regime": 20,
    "confidence_pct": 99.7,
    "nifty_close": 22231.8,
    "nifty_change_pct": -1.64,
    "from_52w_high_pct": -15.56,
    "ytd_pct": -14.92,
    "signals": ["Daily price swings are larger than usual", "NIFTY is well below its recent high"],
}


def test_template_brief():
    text, changed = briefs.template_brief(FACTS)
    assert "22,231.80" in text and "-1.64%" in text and "20 trading days" in text
    assert "NIFTY is well below" in text and "daily price swings" in text
    assert changed.startswith("No regime change")
    assert briefs.check_brief(text, changed, FACTS) == []
    flipped = {**FACTS, "previous_regime": "Bull", "days_in_regime": 1}
    t2, c2 = briefs.template_brief(flipped)
    assert "1 trading day " in t2 and c2 == "The regime changed from Bull to Sideways."


def test_brief_checks():
    """TC-AGT-10 logic: invented numbers, advice words or bad length are rejected."""
    good = (
        "On 2026-10-08 NIFTY 50 closed at 22,231.8, down 1.64% on the day. The model sees a Sideways "
        "market for 20 trading days, with 99.7% confidence, as daily swings grew larger and NIFTY sat "
        "well below its 52-week high."
    )
    assert briefs.check_brief(good, "No change since yesterday.", FACTS) == []
    invented = good.replace("20 trading days", "45 trading days")
    assert any("45" in p for p in briefs.check_brief(invented, None, FACTS))
    advice = good + " Investors should buy the dip."
    assert any("banned" in p for p in briefs.check_brief(advice, None, FACTS))
    assert any("words" in p for p in briefs.check_brief("Too short.", None, FACTS))


def test_guard():
    """TC-AGT-09: images removed; advice, targets and prompt leaks replaced (MM-LLM-005)."""
    text, warnings, replaced = guard.check("Here is a chart ![x](http://evil/p.png) of NIFTY.")
    assert "![" not in text and replaced and warnings == ["MM-LLM-005"]
    assert guard.check("Contact me at a@b.com")[0] == "Contact me at [removed]"
    assert guard.check("key AIza" + "A" * 35)[0] == "key [removed]"
    for bad in ("You should sell your index fund now.", "Buy RELIANCE today", "The target price is 3000"):
        text, _, replaced = guard.check(bad)
        assert replaced and text == guard.SAFE_ADVICE
    assert guard.check(f"My rules [{CANARY}] are...")[0] == guard.SAFE_LEAK
    ok = "As of 2026-10-08 the market is Sideways. Please speak to a SEBI-registered adviser."
    assert guard.check(ok) == (ok, [], False)
