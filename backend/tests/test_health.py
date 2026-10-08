"""TC-OPS: the liveness endpoint answers without any external dependency."""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app


def test_livez_returns_ok_and_version():
    response = TestClient(app).get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
