"""model_registry and pipeline_runs: which model is live, and what each job did.

model_registry holds one row per released model with the SHA-256 of each file; exactly one
row has is_active = true (a partial unique index enforces it). Inference always loads the
active row's files and refuses them if a checksum does not match (MM-MODEL-001).
"""

import json
import logging

from psycopg.types.json import Jsonb

from marketmood_ml.common import MM_MODEL_004, PipelineError

log = logging.getLogger("registry")

STATUSES = ("validated", "experimental", "retired")

REGISTER_SQL = """
INSERT INTO model_registry (
    version, status, train_start, train_end, data_end, config, metrics, label_map,
    artifact_path, checksums, is_active
)
VALUES (%(version)s, %(status)s, %(train_start)s, %(train_end)s, %(data_end)s, %(config)s,
        %(metrics)s, %(label_map)s, %(artifact_path)s, %(checksums)s, %(is_active)s)
ON CONFLICT (version) DO UPDATE SET
    status = EXCLUDED.status,
    metrics = EXCLUDED.metrics,
    is_active = EXCLUDED.is_active
WHERE model_registry.checksums = EXCLUDED.checksums
RETURNING version;
"""

DEACTIVATE_SQL = "UPDATE model_registry SET is_active = false WHERE is_active AND version <> %s;"

ACTIVE_SQL = """
SELECT version, status, artifact_path, checksums, label_map
FROM model_registry
WHERE is_active;
"""

RECORD_RUN_SQL = """
INSERT INTO pipeline_runs (job, started_at, finished_at, status, rows, error)
VALUES (%s, %s, now(), %s, %s, %s);
"""


def registry_params(model, checksums, artifact_path, status, activate):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    return {
        "version": model.version,
        "status": status,
        "train_start": model.train["start"],
        "train_end": model.train["end"],
        "data_end": model.train["test_end"],
        "config": Jsonb(model.config),
        "metrics": Jsonb(json.loads(json.dumps(model.metrics))),
        "label_map": Jsonb({str(k): v for k, v in model.label_map.items()}),
        "artifact_path": artifact_path,
        "checksums": Jsonb(checksums),
        "is_active": activate,
    }


def register(conn, model, checksums, artifact_path, status, activate=True):
    """Insert (or re-activate) a model version. A version can never change its files."""
    params = registry_params(model, checksums, artifact_path, status, activate)
    with conn.cursor() as cur:
        if activate:
            cur.execute(DEACTIVATE_SQL, (model.version,))
        cur.execute(REGISTER_SQL, params)
        if cur.fetchone() is None:
            raise PipelineError(
                MM_MODEL_004,
                f"{model.version} is already registered with different files; "
                "train under a new version (mm-train --version) instead of overwriting",
            )
    log.info("Registered %s (%s)%s.", model.version, status, ", now active" if activate else "")


def get_active(conn):
    """Return the active model row as a dict, or None if nothing is registered yet."""
    with conn.cursor() as cur:
        cur.execute(ACTIVE_SQL)
        row = cur.fetchone()
    if row is None:
        return None
    version, status, artifact_path, checksums, label_map = row
    return {
        "version": version,
        "status": status,
        "artifact_path": artifact_path,
        "checksums": checksums,
        "label_map": label_map,
    }


def record_run(url, job, started_at, status, rows=None, error=None):
    """Write one pipeline_runs row on its own connection (so a failed job can still log)."""
    from marketmood_ml.common import db_connection

    try:
        with db_connection(url) as conn, conn.cursor() as cur:
            cur.execute(
                RECORD_RUN_SQL,
                (job, started_at, status, Jsonb(rows or {}), None if error is None else str(error)[:2000]),
            )
    except Exception as exc:  # logging the run must never hide the real outcome
        log.warning("Could not record the %s run in pipeline_runs: %s", job, exc)
