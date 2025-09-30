# tests/test_auth_onboarding.py
from fastapi.testclient import TestClient

API = "/api/v1"

def test_me_initial(client: TestClient, auth_headers):
    r = client.get(f"{API}/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "user" in data and "roles" in data and "active" in data

def test_register_profile(client: TestClient, auth_headers):
    # save name & email
    r = client.post(f"{API}/users/register",
                    headers=auth_headers,
                    json={"name": "Ava", "email": "ava@example.com"})
    assert r.status_code == 200, r.text
    # read back via /me
    r = client.get(f"{API}/me", headers=auth_headers)
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["name"] == "Ava"
    assert user["email"] == "ava@example.com"
