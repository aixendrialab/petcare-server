# tests/test_register_parent.py
import os
import uuid
from typing import Dict
from starlette.testclient import TestClient
import jwt

API = "/api/v1"
FIXED_OTP = os.getenv("FIXED_OTP", "123456")

def bearer(t: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {t}"}

def test_register_parent_happy_path(client, unique_email):
    new_phone = "09" + uuid.uuid4().hex[:10]

    # 1) Verify → ACTUAL token (server creates minimal user if missing)
    r = client.post(f"{API}/auth/otp/verify", json={"phone": new_phone, "otp": FIXED_OTP})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("type") == "actual", out
    assert out.get("token"), out
    token = out["token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert not claims.get("pre", False)

    # 2) Register basic profile
        # ... get token ...
    email = unique_email(prefix="new.parent", domain="example.com")
    r = client.post(f"{API}/users/register", headers=bearer(token),
                    json={"name": "New Parent User", "email": email})
    """
    New user -> verify OTP (ACTUAL token, user row created)
             -> POST /users/register (name/email)
             -> PUT /me/pets (two pets)
             -> POST /me/active {role: parent}
             -> /auth/me reflects roles & active
    """
    assert r.status_code in (200, 204), r.text

    # 3) Add/replace pets
    payload_pets = {
        "pets": [
            {
                "name": "Milo",
                "breed": "Beagle",
                "dob": "2022-03-10",
                "gender": "male",
                "vaccine_status": "up_to_date",
                "rewards": "Very Good Boy",
                # picture_url optional in test
            },
            {
                "name": "Luna",
                "breed": "Persian Cat",
                "dob": "2020-12-01",
                "gender": "female",
                "vaccine_status": "due",
                "rewards": "Calm Queen",
            },
        ]
    }
    r = client.put(f"{API}/me/pets", headers=bearer(token), json=payload_pets)
    assert r.status_code in (200, 204), r.text

    # 4) Ensure/activate role = parent (should upsert role if absent)
    r = client.post(f"{API}/me/active", headers=bearer(token), json={"role": "parent"})
    assert r.status_code == 200, r.text
    act = r.json()
    assert any(rr["role"] == "parent" for rr in act.get("roles", [])), act
    assert act.get("active", {}).get("role") == "parent", act

    # 5) /auth/me reflects the same
    r = client.get(f"{API}/me", headers=bearer(token))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me.get("user") and me["user"].get("phone") == new_phone
    assert any(rr["role"] == "parent" for rr in me.get("roles", []))
    assert me.get("active", {}).get("role") == "parent"
