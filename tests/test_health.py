from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["services"]) == {"qdrant", "redis", "postgres"}
    cap = body["capabilities"]
    assert cap["runtime_mode"] in ("local", "vertex")
    assert "vertex_project_configured" in cap
    assert cap["application_default_credentials_ok"] in (None, True, False)
