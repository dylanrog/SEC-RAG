from fastapi.testclient import TestClient

from api.app import app


def test_healthz_reports_ok():
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
