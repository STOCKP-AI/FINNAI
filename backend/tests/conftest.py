"""Shared fixtures. Unit tests need nothing; DB tests need TEST_DATABASE_URL (a disposable
Postgres with db/migrations applied - CI provides one). Never Supabase: tables are truncated."""

from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import chat as chat_api
from app.core.config import get_settings
from app.main import create_app
from app.services import market
from backend_helpers import TEST_URL, make_settings, seed


@pytest.fixture
def settings():
    return make_settings(database_url=TEST_URL)


@pytest.fixture
def client(settings):
    """App without a database (unit level)."""
    app = create_app(settings, open_db=False)
    app.dependency_overrides[get_settings] = lambda: settings
    db.set_pool(None)
    market.clear_cache()
    chat_api.set_llm(None)
    with TestClient(app) as c:
        yield c
    chat_api.set_llm(None)


@pytest.fixture
def seeded(settings):
    """Seeded disposable database, a pool on it, and an app using both."""
    if "supabase" in (urlparse(TEST_URL).hostname or ""):
        pytest.fail("TEST_DATABASE_URL points at Supabase; use a disposable database")
    pool = db.open_pool(settings)
    pool.wait(timeout=10)
    with db.writer() as conn:
        days = seed(conn)
    market.clear_cache()
    app = create_app(settings, open_db=False)
    app.dependency_overrides[get_settings] = lambda: settings
    chat_api.set_llm(None)
    with TestClient(app) as c:
        yield c, days
    chat_api.set_llm(None)
    market.clear_cache()
    db.close_pool()
