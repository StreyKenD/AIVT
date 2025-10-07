from fastapi.testclient import TestClient

from apps.control_panel_backend.main import app


def test_status_endpoint_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "modules" in payload
