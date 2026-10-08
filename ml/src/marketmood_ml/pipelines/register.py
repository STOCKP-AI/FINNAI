"""Register a released model folder in model_registry and make it the active model.

Usage:
    uv run mm-register ml/models/hmm-20261008-c2              # status from metrics.json
    uv run mm-register ml/models/<version> --status retired --no-activate

Use it to set up a fresh database with a model that is already in Git. The checksums of
the files as they are now become the trusted values, so only register files that came
from a reviewed pull request. Then run mm-infer.
"""

import argparse
import sys
from pathlib import Path

from marketmood_ml.common import (
    MM_DB_001,
    MM_MODEL_001,
    PipelineError,
    db_connection,
    is_database_error,
    load_settings,
    setup_logging,
)
from marketmood_ml.model.artifacts import (
    MODEL_FILES,
    artifact_path,
    load_model,
    resolve_artifact,
    sha256_file,
)
from marketmood_ml.model.registry import STATUSES, register

log = setup_logging("register")


def run(args):
    folder = Path(args.folder)
    if not folder.is_dir():
        folder = resolve_artifact(args.folder)
    if not (folder / "model.json").is_file():
        raise PipelineError(MM_MODEL_001, f"no model folder at {args.folder}")
    checksums = {name: sha256_file(folder / name) for name in MODEL_FILES if (folder / name).is_file()}
    model = load_model(folder, checksums)
    status = args.status or ("validated" if model.metrics.get("passed") else "experimental")
    url = load_settings()
    with db_connection(url) as conn:
        register(conn, model, checksums, artifact_path(folder), status, activate=not args.no_activate)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Register a saved model folder in model_registry.")
    p.add_argument("folder", help="e.g. ml/models/hmm-20261008-c2")
    p.add_argument("--status", choices=STATUSES, help="default: from metrics.json (validated/experimental)")
    p.add_argument("--no-activate", action="store_true", help="register without making it active")
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
