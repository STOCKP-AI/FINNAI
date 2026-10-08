"""Publish the active model's regime labels for the whole history into regime_output.

Usage:
    uv run mm-infer             # recompute every day and upsert; logs the latest regime
    uv run mm-infer --dry-run   # compute and check, write nothing

Every run recomputes the full history with the active model (so history always matches the
model shown), writes only rows whose values changed, and removes rows for dates that are no
longer in features. Running it twice in a row changes nothing. One pipeline_runs row is
written per run (not in --dry-run).
"""

import argparse
import sys
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from marketmood_ml.common import (
    MM_DATA_002,
    MM_DB_001,
    MM_MODEL_003,
    PipelineError,
    db_connection,
    describe_database_url,
    is_database_error,
    load_settings,
    setup_logging,
)
from marketmood_ml.model.artifacts import load_model, resolve_artifact
from marketmood_ml.model.data import load_frame
from marketmood_ml.model.predict import predict_history, validate_output
from marketmood_ml.model.registry import get_active, record_run

log = setup_logging("infer")

COLUMNS = (
    "label",
    "confidence",
    "p_bull",
    "p_sideways",
    "p_crisis",
    "confirmed_label",
    "signals",
    "surrogate_agrees",
    "model_version",
)

UPSERT_SQL = f"""
INSERT INTO regime_output (date, {", ".join(COLUMNS)})
VALUES (%s, {", ".join(["%s"] * len(COLUMNS))})
ON CONFLICT (date) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS)}
WHERE ({", ".join("regime_output." + c for c in COLUMNS)})
    IS DISTINCT FROM ({", ".join("EXCLUDED." + c for c in COLUMNS)});
"""

STALE_SQL = "SELECT count(*) FROM regime_output WHERE NOT (date = ANY(%s));"
DELETE_STALE_SQL = "DELETE FROM regime_output WHERE NOT (date = ANY(%s));"
MAX_STALE_ROWS = 10  # more than this means features lost history: stop instead of deleting


def to_rows(out):
    rows = []
    for r in out.itertuples(index=False):
        rows.append(
            (
                r.date,
                r.label,
                float(r.confidence),
                float(r.p_bull),
                float(r.p_sideways),
                float(r.p_crisis),
                r.confirmed_label,
                Jsonb(r.signals),
                bool(r.surrogate_agrees),
                r.model_version,
            )
        )
    return rows


def upsert(conn, out):
    """Write changed rows, delete stale ones; return (rows changed, rows deleted)."""
    dates = list(out["date"])
    with conn.cursor() as cur:
        cur.execute(STALE_SQL, (dates,))
        stale = cur.fetchone()[0]
        if stale > MAX_STALE_ROWS:
            raise PipelineError(
                MM_DATA_002,
                f"{stale} regime_output rows have no feature row; refusing to delete them "
                "(check the features table first)",
            )
        cur.executemany(UPSERT_SQL, to_rows(out))
        changed = max(cur.rowcount, 0)
        cur.execute(DELETE_STALE_SQL, (dates,))
        deleted = max(cur.rowcount, 0)
    return changed, deleted


def infer(url, dry_run=False):
    """Do the work; return a summary dict (also used by mm-nightly)."""
    log.info("Database: %s", describe_database_url(url))
    with db_connection(url) as conn:
        active = get_active(conn)
        if active is None:
            raise PipelineError(
                MM_MODEL_003, "no active model in model_registry (run mm-train --register first)"
            )
        model = load_model(resolve_artifact(active["artifact_path"]), active["checksums"])
        log.info("Active model %s (%s); checksums verified.", model.version, active["status"])
        frame = load_frame(conn)
        out = predict_history(model, frame)
        errors = validate_output(out)
        if errors:
            raise PipelineError(
                MM_DATA_002, "regime output check failed, nothing written: " + "; ".join(errors)
            )
        last = out.iloc[-1]
        log.info(
            "%d days (%s to %s). Latest %s: %s (confidence %.2f; today's raw label %s). Top signals: %s",
            len(out),
            out["date"].iloc[0],
            last["date"],
            last["date"],
            last["confirmed_label"],
            last["confidence"],
            last["label"],
            ", ".join(f"{s['feature']} {s['direction']}" for s in last["signals"]),
        )
        summary = {
            "model_version": model.version,
            "rows": len(out),
            "latest_date": str(last["date"]),
            "latest_label": last["confirmed_label"],
        }
        if dry_run:
            log.info("Dry run: nothing written.")
            return summary
        changed, deleted = upsert(conn, out)
    log.info("regime_output: %d rows written or changed, %d stale rows removed.", changed, deleted)
    return {**summary, "changed": changed, "deleted": deleted}


def run(args):
    started = datetime.now(UTC)
    url = load_settings()
    try:
        summary = infer(url, args.dry_run)
    except Exception as exc:
        if not args.dry_run:
            record_run(url, "infer", started, "failed", error=f"{type(exc).__name__}: {exc}")
        raise
    if not args.dry_run:
        record_run(url, "infer", started, "success", summary)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Write the active model's regime labels to regime_output.")
    p.add_argument("--dry-run", action="store_true", help="compute and check, but write nothing")
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
