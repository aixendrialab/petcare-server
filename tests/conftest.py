import sys
import re
import uuid
import tests._win_event_loop_policy
from pathlib import Path

# Project root = one level above tests/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
import pytest
from fastapi.testclient import TestClient

# Important: your FastAPI app object should be created in app/main.py as `app`
# and it should include the router with the /auth/* paths.
from app.main import app  # ensure /api/v1 router is included there

API = "/api/v1"
FIXED_OTP = "123456"

@pytest.fixture(autouse=True)
def _freeze_utc_now(monkeypatch):
    # Pick a deterministic “now” only for tests that care.
    # Example: 09:05Z so 60m lead hides 09:00 & 09:30
    monkeypatch.setenv("UTC_NOW_OVERRIDE", "2025-10-13T09:05:00Z")
    yield
    monkeypatch.delenv("UTC_NOW_OVERRIDE", raising=False)
    
def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def api():
    return API

@pytest.fixture(scope="session")
def client():
    return TestClient(app)

@pytest.fixture
def phone() -> str:
    # use a random-ish number each run to avoid cross-test pollution in dev memory
    return "+919999"

@pytest.fixture
def fixed_otp() -> str:
    # backend hardcodes 123456 in dev stub
    return FIXED_OTP

@pytest.fixture
def new_phone() -> str:
    return "09" + uuid.uuid4().hex[:10]

@pytest.fixture
def auth_token_new(new_phone: str) -> str:
    """
    Creates a fresh token using a local TestClient so it does NOT
    depend on the 'client' fixture (prevents circular dependency).
    """
    c = TestClient(app)

    # If you have a request step, it's safe to call—but not required for the fixed OTP.
    # c.post(f"{API}/auth/otp/request", json={"phone": new_phone})

    # Verify with the *otp* field (not 'code')
    r = c.post(f"{API}/auth/otp/verify", json={"phone": new_phone, "otp": "123456"})
    assert r.status_code == 200, r.text
    return r.json()["token"]

@pytest.fixture
def client(auth_token_new):
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {auth_token_new}"})
    return c

@pytest.fixture
def auth_token(client, phone, fixed_otp) -> str:
    # request OTP (creates placeholder user)
    r = client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text

    # verify OTP -> token
    r = client.post(f"{API}/auth/otp/verify", json={"phone": phone, "otp": fixed_otp})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "token" in data and data["token"], data
    return data["token"]

@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture
def unique_email():
    """
    Returns a factory that generates RFC-safe unique emails.
    Usage:
        email = unique_email()                          # "user+1a2b3c@example.com"
        email2 = unique_email(prefix="parent")          # "parent+4d5e6f@example.com"
        email3 = unique_email(domain="test.local")      # "user+7a8b9c@test.local"
    """
    def _make(prefix: str = "user", domain: str = "example.com") -> str:
        # normalize & keep it RFC-friendly
        prefix = re.sub(r"[^a-z0-9._-]", "", prefix.lower()) or "user"
        domain = re.sub(r"[^a-z0-9._-]", "", domain.lower()) or "example.com"
        return f"{prefix}+{uuid.uuid4().hex[:8]}@{domain}"
    return _make