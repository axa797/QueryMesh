from api.main import app
from fastapi.testclient import TestClient


def test_query_401_without_bearer() -> None:
    client = TestClient(app)
    r = client.post("/query", json={"query": "hi"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "invalid_api_key"
    assert "message" in body
