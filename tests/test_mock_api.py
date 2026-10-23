from fastapi.testclient import TestClient

from mock_ticketing.app import app

client = TestClient(app)


def token():
    r = client.post("/oauth/token", data={"grant_type": "client_credentials"}, auth=("field-agent", "local-dev-secret"))
    assert r.status_code == 200
    return r.json()["access_token"]


def test_bad_client_secret_is_rejected():
    r = client.post("/oauth/token", data={"grant_type": "client_credentials"}, auth=("field-agent", "wrong"))
    assert r.status_code == 401


def test_tickets_require_bearer_token():
    assert client.get("/api/tickets").status_code == 401


def test_list_and_get_tickets():
    h = {"Authorization": f"Bearer {token()}"}
    open_ids = [t["id"] for t in client.get("/api/tickets", params={"status": "open"}, headers=h).json()["tickets"]]
    assert "INC-1042" in open_ids and "INC-1038" not in open_ids
    assert client.get("/api/tickets/INC-1038", headers=h).json()["severity"] == "Sev 1"
    assert client.get("/api/tickets/INC-9999", headers=h).status_code == 404
