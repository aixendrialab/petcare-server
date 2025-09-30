# tests/test_security.py
import os
import uuid
import jwt
from starlette.testclient import TestClient

API = "/api/v1"
FIXED_OTP = os.getenv("FIXED_OTP", "123456")

def bearer(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}

def test_security_three_paths(client: TestClient):
    """
    Exercise current_user_id through:
      - real JWT (via /auth/otp/verify)
      - dev-uid token
      - X-User-Id header
    We call a benign authed endpoint: GET /users/vet/locations
    """
    # 1) Real JWT: create a new user via OTP verify
    new_phone = "09" + uuid.uuid4().hex[:10]
    r = client.post(f"{API}/auth/otp/verify", json={"phone": new_phone, "otp": FIXED_OTP})
    assert r.status_code == 200, r.text
    token = r.json().get("token")
    assert token

    # Call vet endpoint with real JWT
    r = client.get(f"{API}/users/vet/locations", headers=bearer(token))
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list) or "locations" in r.json() or isinstance(r.json(), dict)

    # Discover user id for dev/X-User-Id scenarios
    me = client.get(f"{API}/auth/me", headers=bearer(token)).json()
    uid = me["user"]["id"]

    # 2) dev-uid:<id>
    r = client.get(f"{API}/users/vet/locations", headers=bearer(f"dev-uid:{uid}"))
    assert r.status_code == 200, r.text

    # 3) X-User-Id
    r = client.get(f"{API}/users/vet/locations", headers={"X-User-Id": str(uid)})
    assert r.status_code == 200, r.text
