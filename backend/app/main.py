"""MarketMood API entry point.

Run locally:  uv run uvicorn app.main:app --reload     (docs at http://localhost:8000/docs)

Endpoints: /livez, /readyz, /v1/regime/{today,history,episodes}, POST /v1/chat (SSE).
Configuration: environment variables / .env files (app/core/config.py).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, db
from app.api import chat, health, regime
from app.core import errors
from app.core.config import get_settings
from app.core.middleware import ApiMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def create_app(settings=None, open_db=True):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app):
        if open_db:
            db.open_pool(settings)
        problem = settings.llm().problem
        if problem:
            logging.getLogger("api").error("MM-CFG-001: %s; chat will answer 503 until fixed.", problem)
        yield
        if open_db:
            db.close_pool()

    app = FastAPI(
        title="MarketMood API",
        version=__version__,
        description="Market-regime data and an educational AI analyst. Not investment advice.",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    errors.install(app)
    app.include_router(health.router)
    app.include_router(regime.router)
    app.include_router(chat.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # exact origins only, never a wildcard
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(ApiMiddleware)
    return app


app = create_app()
