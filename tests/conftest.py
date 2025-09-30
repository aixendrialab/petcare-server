# tests/conftest.py
# tests/conftest.py
import sys
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

@pytest.fixture(scope="session")
def client():
    return TestClient(app)

@pytest.fixture
def phone() -> str:
    # use a random-ish number each run to avoid cross-test pollution in dev memory
    return "09840185469"

@pytest.fixture
def fixed_otp() -> str:
    # backend hardcodes 123456 in dev stub
    return "123456"

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
