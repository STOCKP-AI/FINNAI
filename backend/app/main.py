"""MarketMood API entry point.

Run locally:  uv run uvicorn app.main:app --reload
Phase 4 adds /v1/regime, /v1/chat and /readyz (database check); only liveness exists now.
"""

from fastapi import FastAPI

from app import __version__

app = FastAPI(title="MarketMood API", version=__version__)


@app.get("/livez", tags=["health"])
def livez() -> dict[str, str]:
    """Liveness: the process is up. Never touches the database or other services."""
    return {"status": "ok", "version": __version__}
