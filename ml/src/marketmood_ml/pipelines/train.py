"""Train the regime model: run the pre-registered sweep, pick the release, save and report.

Usage:
    uv run mm-train                         # data from Supabase; writes ml/models/<version>/,
                                            # docs/validation.md and docs/validation_chart.svg
    uv run mm-train --config C2             # train one configuration only
    uv run mm-train --csv export.csv        # offline input (date, 8 features, close)
    uv run mm-train --register              # also register the model and make it active
    uv run mm-train --register --allow-experimental
                                            # register even if a Gate G2 target is missed
    uv run mm-train --version hmm-20261008-c2b  # a new name (released versions never change)

Training never writes regime_output; run mm-infer after registering. A model that misses a
gate is saved but not registered (MM-MODEL-002, the current model stays active) unless
--allow-experimental is given; it is then registered with status "experimental".
"""

import argparse
import sys
from pathlib import Path

from marketmood_ml.common import (
    MM_DB_001,
    MM_MODEL_002,
    PipelineError,
    db_connection,
    describe_database_url,
    is_database_error,
    load_settings,
    setup_logging,
)
from marketmood_ml.model.artifacts import MODELS_DIR, REPO_ROOT, artifact_path, save_model
from marketmood_ml.model.config import CONFIGS, get_config
from marketmood_ml.model.data import load_frame, load_frame_csv
from marketmood_ml.model.registry import register
from marketmood_ml.model.report import validation_markdown, validation_svg
from marketmood_ml.model.trainer import run_sweep, select, walk_forward

log = setup_logging("train")

DOCS_DIR = REPO_ROOT / "docs"


def run(args):
    url = None
    if args.csv:
        frame = load_frame_csv(args.csv)
        log.info("Loaded %d rows from %s.", len(frame), args.csv)
    else:
        url = load_settings()
        log.info("Database: %s", describe_database_url(url))
        with db_connection(url) as conn:
            frame = load_frame(conn)
        log.info(
            "Loaded %d feature rows (%s to %s).",
            len(frame),
            frame["date"].min().date(),
            frame["date"].max().date(),
        )

    configs = [get_config(args.config)] if args.config else list(CONFIGS)
    results = run_sweep(frame, configs)
    chosen = select(results)
    config, model, out, metrics = chosen
    if args.version:
        model.version = args.version
        out["model_version"] = args.version
    if not args.no_walk_forward:
        log.info("Walk-forward check for %s (refit each year on earlier years only)...", config.name)
        metrics["walk_forward"] = walk_forward(frame, config)
        wf = metrics["walk_forward"]
        if wf:
            log.info(
                "Walk-forward %s to %s: periods %d/%d, macro-F1 %.3f, switches/yr %.1f, 2020 lag %s",
                wf["start"],
                wf["end"],
                wf["periods_correct"],
                wf["periods_scored"],
                wf["macro_f1"],
                wf["switches_per_year"],
                wf["transition_lag_2020"],
            )
    status = "validated" if metrics["passed"] else "experimental"
    folder = Path(args.out) / model.version
    checksums = save_model(model, folder)
    failed = [k for k, v in metrics["gates"].items() if not v]
    log.info(
        "Released %s (%s)%s -> %s",
        model.version,
        status,
        "" if not failed else "; gates not met: " + ", ".join(failed),
        folder,
    )

    if not args.no_report:
        docs = Path(args.docs)
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "validation.md").write_text(
            validation_markdown(results, chosen, status), encoding="utf-8", newline="\n"
        )
        (docs / "validation_chart.svg").write_text(
            validation_svg(frame, out, model.train["test_start"]), encoding="utf-8", newline="\n"
        )
        log.info("Wrote %s and %s.", docs / "validation.md", docs / "validation_chart.svg")

    if args.register:
        if status != "validated" and not args.allow_experimental:
            raise PipelineError(
                MM_MODEL_002,
                f"{model.version} misses {', '.join(failed)}; not registered, the active model is kept "
                "(use --allow-experimental to register it as experimental)",
            )
        url = url or load_settings()
        with db_connection(url) as conn:
            register(conn, model, checksums, artifact_path(folder), status)
    return 0


def parse_args(argv):
    p = argparse.ArgumentParser(description="Train, evaluate and save the market-regime model.")
    p.add_argument("--config", help="train one configuration (default: the whole pre-registered sweep)")
    p.add_argument("--csv", help="read the input from a CSV file instead of the database")
    p.add_argument("--out", default=str(MODELS_DIR), help="folder for model versions (default ml/models)")
    p.add_argument("--docs", default=str(DOCS_DIR), help="folder for validation.md and the chart")
    p.add_argument("--no-report", action="store_true", help="do not write the validation report")
    p.add_argument("--register", action="store_true", help="register the model and make it active")
    p.add_argument("--allow-experimental", action="store_true", help="register even if a gate is missed")
    p.add_argument("--version", help="version name (default hmm-<last data date>-<config>)")
    p.add_argument("--no-walk-forward", action="store_true", help="skip the yearly out-of-sample refits")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
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
