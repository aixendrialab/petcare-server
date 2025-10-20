# tests/test_auth_verify_existing_user.py
from typing import Optional
from fastapi.testclient import TestClient
import os

from tests.helpers.seed_data import seed_phone

API = "/api/v1"

def _seed_phone() -> str:
    """
    Prefer an env var so CI/dev can change the seed account easily.
    Falls back to the seeded phone you've been using in examples.
    """
    return os.getenv("SEED_EXISTING_PHONE", "+919999")

def _extract_test_otp(resp_json: dict) -> Optional[str]:
    """
    In test/dev mode many backends return the OTP (or a fixed OTP like '0000').
    Try to read it if present; otherwise default to '0000'.
    Adjust if your /auth/otp/request returns a different field.
    """
    for k in ("otp", "test_otp", "debug_otp"):
        if k in resp_json and isinstance(resp_json[k], str):
            return resp_json[k]
    return "0000"

# tests/test_auth_onboarding.py

def test_verify_existing_user_returns_actual_token_and_roles(client, fixed_otp):
    """Existing user -> type=actual, token present, roles is a non-empty list containing expected roles."""
    API = "/api/v1"
    phone = seed_phone()  # Asha from seed (has role 'parent')

    # Request OTP (your backend creates/ensures placeholder, OK to call for an existing phone)
    r = client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text

    # Verify with fixed OTP -> should return actual token + roles
    r = client.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": fixed_otp})
    assert r.status_code == 200, r.text
    body = r.json()

    # Shape assertions
    assert body.get("type") == "actual", body
    assert body.get("token"), "Expected a real token for existing user"

    # Roles must be present per implementation and contain user's roles
    # Your /auth/otp/verify returns roles from user_roles when user exists
    roles = body.get("roles")
    assert isinstance(roles, list), body
    assert any(r.get("role") == "parent" for r in roles), f"Expected 'parent' in roles, got: {roles}"

    # Optional: if active role is set in DB, response may include it.
    # We don't require it, but if present it must be shaped like {"role": "..."}
    if "active" in body and body["active"] is not None:
        assert isinstance(body["active"], dict) and "role" in body["active"], body

