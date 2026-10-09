"""API, tools, chat, brief and evals against a seeded disposable Postgres (TEST_DATABASE_URL)."""

import json
from datetime import date

import psycopg
import pytest

from app import brief, db
from app.agent import store, tools
from app.agent.llm import Done, LLMError, TextDelta, ToolCall
from app.api import chat as chat_api
from app.evals import run as evals
from app.services import market
from backend_helpers import TEST_URL, make_settings, needs_db, seed, sse_events

pytestmark = [pytest.mark.integration, needs_db]


def test_today_schema_as_of_and_brief(seeded):
    """TC-API-01: 200, schema-valid, as_of and is_stale present."""
    c, days = seeded
    r = c.get("/v1/regime/today")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=300"
    body = r.json()
    assert body["as_of"] == days[-1].isoformat() and body["is_stale"] in (True, False)
    reg = body["regime"]
    assert reg["label"] == "Bull" and reg["days_in_regime"] == 50 and reg["since"] == days[250].isoformat()
    assert body["signals"][0]["name"] == "India VIX" and body["signals_approximate"] is True
    assert body["brief"]["source"] == "template" and "NIFTY 50 closed at" in body["brief"]["text"]
    assert body["model"] == {"version": "hmm-test", "status": "experimental"}
    with db.writer() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO daily_briefs (date, brief, what_changed, source) "
            "VALUES (%s, 'AI text', 'none', 'llm')",
            (days[-1],),
        )
    market.clear_cache()
    assert c.get("/v1/regime/today").json()["brief"] == {
        "text": "AI text",
        "what_changed": "none",
        "source": "llm",
    }


def test_old_data_is_stale(settings):
    """TC-API-02: latest regime older than the last trading day -> is_stale = true."""
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    pool = db.open_pool(settings)
    pool.wait(timeout=10)
    with db.writer() as conn:
        seed(conn, end=date(2026, 9, 1))
    market.clear_cache()
    app = create_app(settings, open_db=False)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        body = c.get("/v1/regime/today").json()
    db.close_pool()
    assert body["is_stale"] is True and body["warnings"] == ["MM-DATA-001"]


def test_history_ranges(seeded):
    """TC-API-03: <= 500 points, ordered by date."""
    c, days = seeded
    full = c.get("/v1/regime/history?range=max").json()
    dates = [p["date"] for p in full["points"]]
    assert len(dates) == len(days) <= 500 and dates == sorted(dates)
    assert set(full["points"][0]) == {"date", "label", "confidence", "close"}
    short = c.get("/v1/regime/history?range=60d").json()["points"]
    assert 38 <= len(short) <= 45 and short[-1]["date"] == days[-1].isoformat()


def test_episodes_endpoint(seeded):
    c, _ = seeded
    body = c.get("/v1/regime/episodes?regime=Crisis").json()
    assert len(body["episodes"]) == 1 and body["episodes"][0]["days"] == 30
    all_eps = c.get("/v1/regime/episodes?limit=2").json()["episodes"]
    assert len(all_eps) == 2 and all_eps[0]["ongoing"] and all_eps[0]["start"] > all_eps[1]["start"]
    assert c.get("/v1/regime/episodes?regime=Bear").status_code == 422


def test_readyz_ok_with_database(seeded):
    c, _ = seeded
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {
        "database": "ok",
        "model": "hmm-test",
        "llm": "mock:mock",
    }


def test_reader_role_cannot_write_or_read_chat_data(seeded):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.reader() as conn:
        conn.execute("SELECT count(*) FROM chat_messages")
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), db.reader() as conn:
        conn.execute("DELETE FROM glossary")
    with db.reader() as conn:
        assert db.fetch_one(conn, "SELECT count(*) AS n FROM regime_output")["n"] == 300


def test_all_tools_against_the_database(seeded):
    _, days = seeded
    s = make_settings(database_url=TEST_URL)

    def ok(name, **args):
        result, status, _ = tools.run_tool(s, name, json.dumps(args))
        assert status == "ok", result
        return result

    cur = ok("get_current_regime")
    assert cur["regime"] == "Bull" and cur["confidence_pct"] == 98.0 and cur["model_status"] == "experimental"
    hist = ok("get_regime_history", days=3650)
    assert len(hist["points"]) <= 120 and hist["regime_changes"][0] == {
        "date": days[120].isoformat(),
        "from": "Bull",
        "to": "Sideways",
    }
    assert ok("get_historical_episodes", regime="Sideways", limit=10)["episodes"][0]["trading_days"] == 40
    fwd = ok("get_forward_returns", regime="Crisis", horizon_days=21)
    assert fwd["n"] == 1 and "caution" in fwd["note"]
    sig = ok("explain_signals")
    assert sig["explanation_is_approximate"] and "percentile" in sig["signals"][0]
    assert ok("explain_signals", date=days[150].isoformat())["regime"] == "Sideways"
    assert "error" in ok("explain_signals", date="2000-01-01")
    assert ok("get_nifty_stats")["as_of"] == days[-1].isoformat()
    assert ok("lookup_glossary", term="VIX")["term"] == "india vix"
    assert ok("lookup_glossary", term="sharpe")["term"] == "sharpe ratio"
    missing = ok("lookup_glossary", term="beta")
    assert "available_terms" in missing and "drawdown" in missing["available_terms"]


def test_chat_end_to_end_with_server_side_history(seeded):
    """TC-AGT-01 (mock) and TC-AGT-08: history comes from the database, not the client."""
    c, days = seeded
    r = c.post("/v1/chat", json={"message": "What regime is the market in today?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "tool_start" and kinds[-1] == "done" and "token" in kinds
    text = "".join(d["text"] for e, d in events if e == "token")
    assert "Bull" in text and days[-1].isoformat() in text
    done = events[-1][1]
    assert (
        done["label"] == "AI-generated · educational only" and done["quota_left"] == 9 and not done["cached"]
    )
    session = done["session_id"]

    seen = []

    class Spy:
        model = "spy"

        async def stream(self, system, messages, tools=None):
            seen.append(messages)
            yield TextDelta("ok")
            yield Done("stop", 1, 1)

    chat_api.set_llm(Spy())
    c.post("/v1/chat", json={"session_id": session, "message": "And yesterday?"})
    history = seen[0]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[0]["content"] == "What regime is the market in today?" and "Bull" in history[1]["content"]

    # a session id from another client starts a fresh conversation (no history leak)
    assert str(store.ensure_session(session, "someone-else")) != session
    assert str(store.ensure_session(session, store_hash(c))) == session


def test_quota_limit_and_refund(seeded):
    c, _ = seeded
    settings = make_settings(database_url=TEST_URL, chat_daily_limit=2)
    from app.core.config import get_settings

    c.app.dependency_overrides[get_settings] = lambda: settings

    class Failing:
        model = "failing"

        async def stream(self, system, messages, tools=None):
            raise LLMError("MM-LLM-002", "rate limited")
            yield  # pragma: no cover

    chat_api.set_llm(Failing())
    events = sse_events(c.post("/v1/chat", json={"message": "hi"}).text)
    assert events == [
        (
            "error",
            {
                "code": "MM-LLM-002",
                "message": events[0][1]["message"],
                "session_id": events[0][1]["session_id"],
            },
        )
    ]
    chat_api.set_llm(None)
    assert sse_events(c.post("/v1/chat", json={"message": "hi"}).text)[-1][1]["quota_left"] == 1  # refunded
    assert sse_events(c.post("/v1/chat", json={"message": "hi"}).text)[-1][1]["quota_left"] == 0
    r = c.post("/v1/chat", json={"message": "hi"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "MM-QUOTA-001"


def test_chip_answers_are_cached_and_free(seeded):
    c, _ = seeded
    first = sse_events(c.post("/v1/chat", json={"message": "x", "chip_id": "today"}).text)
    assert not first[-1][1]["cached"] and first[-1][1]["quota_left"] == 9
    second = sse_events(c.post("/v1/chat", json={"message": "anything", "chip_id": "today"}).text)
    assert second[-1][1]["cached"] and second[-1][1]["quota_left"] is None
    text1 = "".join(d["text"] for e, d in first if e == "token").strip()
    text2 = "".join(d["text"] for e, d in second if e == "token").strip()
    assert text1 == text2
    with db.writer() as conn:
        assert db.fetch_one(conn, "SELECT chats FROM usage_daily")["chats"] == 1


def test_guard_replaces_advice_and_marks_done(seeded):
    c, _ = seeded

    class Adviser:
        model = "bad"

        async def stream(self, system, messages, tools=None):
            yield TextDelta("You should sell your fund today. ![p](http://x/p.png)")
            yield Done("stop")

    chat_api.set_llm(Adviser())
    done = sse_events(c.post("/v1/chat", json={"message": "Should I sell?"}).text)[-1][1]
    assert done["warnings"] == ["MM-LLM-005"] and done["replace_text"].startswith("I can't give personal")
    with db.writer() as conn:
        stored = db.fetch_one(
            conn, "SELECT content FROM chat_messages WHERE role = 'assistant' ORDER BY id DESC"
        )
    assert stored["content"] == done["replace_text"]


def test_chat_heartbeat_and_timeout(seeded, monkeypatch):
    c, _ = seeded

    class Slow:
        model = "slow"

        async def stream(self, system, messages, tools=None):
            import asyncio

            await asyncio.sleep(0.3)
            yield TextDelta("late")
            yield Done("stop")

    chat_api.set_llm(Slow())
    monkeypatch.setattr(chat_api, "HEARTBEAT_S", 0.1)
    monkeypatch.setattr(chat_api, "_with_heartbeat", _fast_heartbeat(chat_api._with_heartbeat))
    body = c.post("/v1/chat", json={"message": "hi"}).text
    assert ": ping" in body and "late" in body
    monkeypatch.setattr(chat_api, "STREAM_LIMIT_S", 0.05)
    events = sse_events(c.post("/v1/chat", json={"message": "hi"}).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "MM-LLM-001"


def _fast_heartbeat(original):
    def wrapper(events, interval=0.1):
        return original(events, 0.1)

    return wrapper


def test_tool_loop_through_the_api(seeded):
    c, _ = seeded

    class OneTool:
        model = "one-tool"

        def __init__(self):
            self.round = 0

        async def stream(self, system, messages, tools=None):
            self.round += 1
            if self.round == 1:
                yield ToolCall("t1", "get_nifty_stats", "{}")
                yield Done("tool_calls", 5, 1)
            else:
                yield TextDelta(f"Close {json.loads(messages[-1]['content'])['close']}")
                yield Done("stop", 9, 3)

    chat_api.set_llm(OneTool())
    events = sse_events(c.post("/v1/chat", json={"message": "stats"}).text)
    assert [e for e, _ in events][:2] == ["tool_start", "tool_end"] and events[1][1]["ok"] is True
    assert events[-1][1]["usage"] == {"in": 14, "out": 4}


def test_brief_cli(seeded):
    _, days = seeded
    rows = market.series()[0]["rows"]
    text, changed, source, model, problems = brief.make_brief(rows, None)
    assert source == "template" and model is None and problems == []

    class GoodWriter:
        model = "writer"

        async def stream(self, system, messages, tools=None):
            facts = json.loads(messages[0]["content"].split("Facts:")[1])
            yield TextDelta(
                f"On {facts['date']} NIFTY 50 closed at {facts['nifty_close']}. "
                f"The model reads the market as {facts['regime']} for {facts['days_in_regime']} "
                f"trading days, with {facts['confidence_pct']}% "
                "confidence, as fear stays low and prices keep a steady upward path in calm trading."
                "\nWHAT_CHANGED: Nothing changed since the previous trading day."
            )

    text, changed, source, model, _ = brief.make_brief(rows, GoodWriter())
    assert source == "llm" and model == "writer" and changed.startswith("Nothing changed")

    class Inventor(GoodWriter):
        async def stream(self, system, messages, tools=None):
            yield TextDelta("NIFTY will rise 25% next month. " * 8)

    assert brief.make_brief(rows, Inventor())[2] == "template"  # TC-AGT-10

    class Broken(GoodWriter):
        async def stream(self, system, messages, tools=None):
            raise LLMError("MM-LLM-003", "boom")
            yield  # pragma: no cover

    assert brief.make_brief(rows, Broken())[2] == "template"


def test_brief_cli_writes(seeded, monkeypatch):
    settings = make_settings(database_url=TEST_URL)
    monkeypatch.setattr(brief, "get_settings", lambda: settings)
    db.close_pool()
    assert brief.main(["--template"]) == 0
    db.open_pool(settings).wait(timeout=10)
    with db.writer() as conn:
        row = db.fetch_one(conn, "SELECT source FROM daily_briefs")
    assert row["source"] == "template"


def test_evals_with_the_mock_model(seeded, tmp_path):
    """The eval harness end to end: the mock passes every rule (no judge configured)."""
    s = make_settings(database_url=TEST_URL)
    import asyncio

    from app.agent.mock import MockClient

    cases = evals.load_cases()
    results = asyncio.run(evals.run_cases(cases, MockClient(), s))
    failed = {r.case["id"]: r.failures for r in results if r.failures or r.error}
    assert len(results) == 20 and not failed
    summary = evals.summarise(results, judged=False)
    assert summary["gate"] and summary["critical"] == 0
    report = evals.report(results, summary, "mock", None)
    assert "| cur-1 | current |" in report and "PASS" in report


def test_eval_rules_and_judge_parsing():
    import asyncio

    case = {
        "id": "x",
        "category": "c",
        "expect_tools": ["get_current_regime"],
        "forbidden": ["(?i)buy"],
        "required": ["%"],
    }
    tools_used = [{"name": "get_current_regime", "result": {"confidence_pct": 98.0, "as_of": "2026-10-08"}}]
    assert evals.check_rules(case, "As of 2026-10-08 confidence is 98%.", tools_used) == []
    fails = evals.check_rules(case, "Buy now, it is 77.7 and " + "word " * 200, [])
    assert any(f.startswith("tools") for f in fails) and any("forbidden" in f for f in fails)
    assert any("required" in f for f in fails) and any("length" in f for f in fails)
    assert any("77.7" in f for f in fails)
    critical = evals.Result({"critical": True}, failures=["x"])
    assert (
        critical.critical
        and evals.Result({}, scores={"clarity": 5, "groundedness": 4, "helpfulness": 3}).score == 4.0
    )

    class Judge:
        async def stream(self, system, messages, tools=None):
            yield TextDelta('Here: {"clarity": 5, "groundedness": 9, "helpfulness": 4, "comment": "ok"}')

    scores = asyncio.run(evals.judge(Judge(), "q", tools_used, "a"))
    assert scores["groundedness"] == 5

    class BadJudge:
        async def stream(self, system, messages, tools=None):
            yield TextDelta("no json")

    with pytest.raises(ValueError):
        asyncio.run(evals.judge(BadJudge(), "q", [], "a"))
    judged = evals.summarise(
        [evals.Result({}, scores={"clarity": 4, "groundedness": 4, "helpfulness": 4})], judged=True
    )
    assert judged["average"] == 4.0 and not judged["gate"]


def store_hash(c):
    """The client hash the API computes for the TestClient's requests."""
    from types import SimpleNamespace

    from app.core.client import client_hash

    req = SimpleNamespace(client=SimpleNamespace(host="testclient"), headers={})
    return client_hash(req, make_settings(database_url=TEST_URL))
