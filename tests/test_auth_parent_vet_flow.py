# tests/integration/test_auth_parent_vet_flow.py
from __future__ import annotations
from fastapi.testclient import TestClient

from tests.conftest import API, bearer, fixed_otp, new_phone

def test_auth_verify_creates_user_and_returns_token(client, new_phone, fixed_otp):
    # OTP verify should create minimal user (if not exists) and return ACTUAL token
    r = client.post(f"{API}/auth/otp/verify", json={"phone": new_phone, "otp": fixed_otp})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("type") == "actual"
    assert isinstance(body.get("token"), str) and body["token"]

def test_parent_register_sets_role_and_pets(client, auth_token_new, unique_email):
    token = auth_token_new
    email = unique_email(prefix="parent")   # e.g., parent+ab12cd34@example.com
    r = client.post(f"{API}/users/register",
                    headers=bearer(token),
                    json={"name": "Test Parent", "email": email})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True

    # replace pets (PUT returns the envelope {pets:[...]})
    payload = {"pets": [{"name": "Coco", "breed": "Lab"}, {"name": "Milo"}]}
    r = client.put(f"{API}/me/pets", headers=bearer(token), json=payload)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("pets"), list)
    assert {"Coco", "Milo"} <= {p["name"] for p in body["pets"]}

    # set active role = parent
    r = client.post(f"{API}/me/active", headers=bearer(token), json={"role": "parent"})
    assert r.status_code == 200
    state = r.json()
    assert state.get("active", {}).get("role") == "parent"
