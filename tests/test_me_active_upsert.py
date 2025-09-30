# tests/test_me_active_upsert.py
import uuid
from starlette.testclient import TestClient

API = "/api/v1"
FIXED_OTP = "123456"

def bearer(t: str): return {"Authorization": f"Bearer {t}"}

def test_me_active_upserts_role_and_sets_active(client: TestClient):
    # Fresh user → ACTUAL token after verify; no roles yet
    phone = "09" + uuid.uuid4().hex[:10]
    r = client.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": FIXED_OTP})
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    # First call should create the 'parent' role (if missing) AND set it active
    r = client.post(f"{API}/me/active", headers=bearer(token), json={"role": "parent"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(rr["role"] == "parent" for rr in body.get("roles", [])), body
    assert body.get("active", {}).get("role") == "parent", body

    # Calling again is idempotent
    r = client.post(f"{API}/me/active", headers=bearer(token), json={"role": "parent"})
    assert r.status_code == 200, r.text
    again = r.json()
    assert again.get("active", {}).get("role") == "parent"

    # Switching roles should update active
    r = client.post(f"{API}/me/active", headers=bearer(token), json={"role": "vet"})
    assert r.status_code in (200, 400)  # depending on whether you allow 'vet' for any user
