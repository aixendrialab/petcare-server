# tests/test_register_vet.py
import os
import uuid
from starlette.testclient import TestClient

API = "/api/v1"
FIXED_OTP = os.getenv("FIXED_OTP", "123456")

def bearer(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}

def test_register_vet_happy_path(client: TestClient):
    """
    New user -> verify OTP (ACTUAL token)
             -> PUT /users/vet/register (profile+locations)
             -> POST /me/active {role:'vet'}
             -> /auth/me shows role+active
    """
    phone = "09" + uuid.uuid4().hex[:10]
    r = client.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": FIXED_OTP})
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    payload = {
        # account layer (optional here, kept minimal)
        "legal_name": "Dr. Vet Person",
        "display_name": "Paws & Claws",
        "business_email": "biz@paws.test",
        "billing_email": "bill@paws.test",
        "billing_address": "123, Pet Street",
        "gstin": "GSTIN123",
        "pan": "PAN123",
        "qualifications": "BVSc & AH",
        "license_no": "LIC123",
        "experience_years": 5,
        "specialties": ["dermatology", "surgery"],
        "visit_in_clinic": True,
        "visit_video": True,
        "fee_in_clinic": 500,
        "fee_video": 400,
        "slot_minutes": 15,
        "locations": [
            {
                "name": "Main Clinic",
                "line1": "12, MG Road",
                "line2": "",
                "city": "Chennai",
                "lat": 13.0827,
                "lng": 80.2707,
                "hours": "Mon–Sat 09:00–18:00",
                "is_primary": True,
            }
        ],
    }

    r = client.put(f"{API}/users/vet/register", headers=bearer(token), json=payload)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out.get("profile"), out
    assert isinstance(out.get("locations"), list), out

    # Ensure/activate vet role (idempotent upsert in your routes)
    r = client.post(f"{API}/me/active", headers=bearer(token), json={"role": "vet"})
    assert r.status_code == 200, r.text
    state = r.json()
    assert any(rr["role"] == "vet" for rr in state.get("roles", [])), state
    assert state.get("active", {}).get("role") == "vet", state

    # /auth/me reflects the same (mirrors parent test pattern)
    r = client.get(f"{API}/auth/me", headers=bearer(token))
    assert r.status_code == 200, r.text
    me = r.json()
    assert any(rr["role"] == "vet" for rr in me.get("roles", [])), me
    assert me.get("active", {}).get("role") == "vet", me
