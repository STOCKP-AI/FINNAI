"""The daily job: ingest -> features -> regime labels, logged as one pipeline_runs row.

Usage:
    uv run mm-nightly            # after 16:00 IST on a trading day
    uv run mm-nightly --dry-run  # download and compute everything, write nothing

Each step is the same code as its own command (mm-ingest, mm-features, mm-infer), and every
step is idempotent, so running the job twice changes nothing. The GitHub Actions schedule
is added in Phase 6.
"""

import argparse
import sys
from argparse import Namespace
from datetime import UTC, datetime

from marketmood_ml.common import MM_DB_001, PipelineError, is_database_error, load_settings, setup_logging
from marketmood_ml.model.registry import record_run
from marketmood_ml.pipelines import features, infer, ingest

log = setup_logging("nightly")


def run(args):
    started = datetime.now(UTC)
    url = load_settings()
    steps = {}
    try:
        ingest.run(Namespace(full=False, start=None, dry_run=args.dry_run))
        steps["ingest"] = "ok"
        features.run(Namespace(dry_run=args.dry_run))
        steps["features"] = "ok"
        steps["infer"] = infer.infer(url, args.dry_run)
    except Exception as exc:
        if not args.dry_run:
            record_run(
                url, "nightly", started, "failed", {"completed": steps}, f"{type(exc).__name__}: {exc}"
            )
        raise
    if not args.dry_run:
        record_run(url, "nightly", started, "success", steps)
    log.info("Nightly job finished: %s", steps)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Ingest, features and regime labels in one run.")
    p.add_argument("--dry-run", action="store_true", help="compute everything, write nothing")
    args = p.parse_args(argv)
    try:
        return run(args)
    except PipelineError as exc:
        log.error("%s", exc)
        return 1
    except Exception as exc:
        if is_database_error(exc):
            log.error("%s: database error: %s", MM_DB_001, exc)
            return 1
        log.exception("Unexpected error")
        return 2


if __name__ == "__main__":
    sys.exit(main())
