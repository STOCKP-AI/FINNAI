"""Liveness and readiness.

/livez  - the process is up; never touches the database (used by the host to restart us).
/readyz - can we serve? Database reachable, an active model registered, AI configured.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import __version__, db
from app.api.schemas import Health
from app.core.config import get_settings
from app.core.errors import ApiError

router = APIRouter(tags=["health"])


@router.get("/livez")
def livez() -> dict[str, str]:
    """Liveness: the process is up. Never touches the database or other services."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz", response_model=Health, responses={503: {"model": Health}})
def readyz(settings=Depends(get_settings)):
    checks = {}
    try:
        with db.reader() as conn:
            row = db.fetch_one(conn, "SELECT version FROM model_registry WHERE is_active")
        checks["database"] = "ok"
        checks["model"] = row["version"] if row else "MM-MODEL-003: no active model"
    except ApiError as exc:
        checks["database"] = exc.code
        checks["model"] = "unknown"
    llm = settings.llm()
    checks["llm"] = f"{llm.provider}:{llm.model}" if llm.problem is None else f"MM-CFG-001: {llm.problem}"
    ok = checks["database"] == "ok" and not checks["model"].startswith("MM-") and "MM-" not in checks["llm"]
    body = {"status": "ok" if ok else "degraded", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)
