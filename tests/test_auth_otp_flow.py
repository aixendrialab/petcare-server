# tests/test_auth_otp_flow.py
import os
import jwt
from fastapi.testclient import TestClient
from tests.helpers.seed_data import seed_phone

API = "/api/v1"

FIXED_OTP = os.getenv("FIXED_OTP", "123456")

def test_verify_existing_user_invalid_otp_rejected(client: TestClient):
    phone = seed_phone()
    r = client.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": "9999"})
    assert r.status_code in (400, 401), r.text

def test_verify_actual_token_for_new_user(client: TestClient):
    # New phone → server creates minimal user (phone only) and returns ACTUAL token
    new_phone = seed_phone()
    r = client.post(f"{API}/auth/otp/verify", json={"phone": new_phone, "otp": FIXED_OTP})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "actual", body
    assert "token" in body and body["token"], body
    # token is not a "pre" token anymore
    claims = jwt.decode(body["token"], options={"verify_signature": False})
    assert claims.get("type") == "actual" or not claims.get("pre", False)
    # roles/active exist (likely []/None for brand new user)
    assert "roles" in body
    assert body.get("active") in (None, {}) or isinstance(body.get("active"), dict)

def test_verify_actual_token_for_existing_user(client: TestClient):
    # Seeded user returns ACTUAL token as well
    seeded = seed_phone()
    r = client.post(f"{API}/auth/otp/verify", json={"phone": seeded, "otp": FIXED_OTP})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "actual"
    assert "token" in body and body["token"]
    claims = jwt.decode(body["token"], options={"verify_signature": False})
    assert not claims.get("pre", False)

def test_verify_invalid_otp(client: TestClient):
    r = client.post(f"{API}/auth/otp/verify", json={"phone": "09990001111", "otp": "BADOTP"})
    assert r.status_code == 400
    assert r.json()["detail"].lower().startswith("invalid otp")
