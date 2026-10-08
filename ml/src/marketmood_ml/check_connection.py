"""Check that DATABASE_URL works and show which kind of connection it is.

Usage: uv run mm-check-db   (or: python -m marketmood_ml.check_connection)

Prints the host, port, user and connection type (never the password), the Postgres
version and the row count and latest date of each pipeline table. Renamed from
test_db.py so that a test runner never mistakes it for a unit test.
"""

import sys

from marketmood_ml.common import (
    PipelineError,
    db_connection,
    describe_database_url,
    load_settings,
    setup_logging,
)

log = setup_logging("check_connection")

TABLES = ["market_data", "features", "regime_output"]


def main():
    try:
        url = load_settings()
    except PipelineError as exc:
        log.error("%s", exc)
        return 1
    log.info("Connecting to %s", describe_database_url(url))
    try:
        with db_connection(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT version();")
            log.info("Connected: %s", cur.fetchone()[0].split(",")[0])
            for table in TABLES:
                cur.execute(f"SELECT count(*), max(date) FROM {table};")
                count, latest = cur.fetchone()
                log.info("%-14s %6d rows, latest %s", table, count, latest)
    except Exception as exc:
        log.error("Connection failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
