# tests/test_auth_onboarding.py
from fastapi.testclient import TestClient
from tests.conftest import API, bearer

def test_me_initial(client: TestClient, auth_headers):
    r = client.get(f"{API}/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "user" in data and "roles" in data and "active" in data

def test_register_profile(client: TestClient, new_phone, unique_email, fixed_otp):
    # fresh user via OTP
    r = client.post(f"{API}/auth/otp/verify", json={"phone": new_phone, "otp": fixed_otp})
    assert r.status_code == 200
    token = r.json()["token"]

    email = unique_email(prefix="new.parent", domain="example.com")
    # save name & email FOR NEW USER
    r = client.post(f"{API}/users/register",
                    headers=bearer(token),
                    json={"name": "Ava", "email": email})
    assert r.status_code == 200, r.text

    # read back via /me
    r = client.get(f"{API}/me", headers=bearer(token))
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["name"] == "Ava" and user["email"] == email
