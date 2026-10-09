"""Write today's dashboard brief into daily_briefs (one LLM call per trading day).

Usage (after mm-nightly / mm-infer):
    uv run mm-brief             # AI brief, checked; template brief if the AI fails the checks
    uv run mm-brief --template  # template brief only (no AI call)
    uv run mm-brief --dry-run   # print, write nothing

The AI may only use the facts it is given: every number in its text must be one of them
(within 0.1), no advice words, 30-90 words (SOA 5.7). Otherwise the template is stored and
MM-LLM-005 is logged. Running it twice for the same day replaces that day's brief.
"""

import argparse
import asyncio
import json
import logging
import sys

from psycopg_pool import PoolTimeout

from app import db
from app.agent.llm import LLMError, TextDelta, make_client
from app.agent.prompts import BRIEF
from app.core.config import get_settings
from app.core.errors import ApiError
from app.services import briefs, market

log = logging.getLogger("brief")

UPSERT_SQL = """
INSERT INTO daily_briefs (date, brief, what_changed, source, model)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (date) DO UPDATE SET brief = EXCLUDED.brief, what_changed = EXCLUDED.what_changed,
    source = EXCLUDED.source, model = EXCLUDED.model, created_at = now();
"""


async def ai_brief(llm, facts):
    """Ask the model; return (brief, what_changed) or raise LLMError / ValueError."""
    prompt = BRIEF.format(facts=json.dumps(facts, indent=1))
    text = ""
    async for ev in llm.stream(
        "You write short, factual market summaries.", [{"role": "user", "content": prompt}]
    ):
        if isinstance(ev, TextDelta):
            text += ev.text
    brief, _, changed = text.partition("WHAT_CHANGED:")
    brief, changed = brief.strip(), changed.strip() or None
    if not brief:
        raise ValueError("empty answer")
    return brief, changed


def make_brief(rows, llm=None):
    """Return (brief, what_changed, source, model, problems)."""
    facts = briefs.brief_facts(rows)
    if llm is not None:
        try:
            text, changed = asyncio.run(ai_brief(llm, facts))
            problems = briefs.check_brief(text, changed, facts)
            if not problems:
                return text, changed, "llm", getattr(llm, "model", None), []
            log.warning("MM-LLM-005: AI brief rejected (%s); using the template.", "; ".join(problems))
        except (LLMError, ValueError) as exc:
            problems = [str(exc)]
            log.warning("AI brief failed (%s); using the template.", exc)
    else:
        problems = []
    text, changed = briefs.template_brief(facts)
    return text, changed, "template", None, problems


def run(args):
    settings = get_settings()
    db.open_pool(settings)
    try:
        try:
            db.get_pool().wait(timeout=15)
        except PoolTimeout as exc:
            raise ApiError("MM-DB-001", "Could not connect to the database.") from exc
        rows = market.series()[0]["rows"]
        llm = None
        if not args.template:
            config = settings.llm()
            if config.problem:
                log.warning("MM-CFG-001: %s; writing the template brief.", config.problem)
            else:
                llm = make_client(config)
        text, changed, source, model, _ = make_brief(rows, llm)
        day = rows[-1]["date"]
        log.info("Brief for %s (%s):\n%s\nWhat changed: %s", day, source, text, changed)
        if args.dry_run:
            log.info("Dry run: nothing written.")
            return 0
        with db.writer() as conn, conn.cursor() as cur:
            cur.execute(UPSERT_SQL, (day, text, changed, source, model))
        log.info("Saved to daily_briefs.")
        return 0
    finally:
        db.close_pool()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Write today's dashboard brief.")
    p.add_argument("--template", action="store_true", help="use the template only (no AI call)")
    p.add_argument("--dry-run", action="store_true", help="print the brief, write nothing")
    args = p.parse_args(argv)
    try:
        return run(args)
    except ApiError as exc:
        log.error("%s: %s", exc.code, exc.message)
        return 1
    except Exception as exc:  # pragma: no cover - last resort
        log.exception("Unexpected error: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
