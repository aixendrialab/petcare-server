from fastapi.testclient import TestClient

API = "/api/v1"

# Pick a phone number that you seed as an existing user
EXISTING_USER_PHONE = "+919999"  # Asha Rao in your seed data

def test_otp_verify_existing_user_returns_actual_and_roles(client: TestClient):
    # 1) Verify OTP for an existing user
    r = client.post(
        f"{API}/auth/otp/verify",
        json={"phone": EXISTING_USER_PHONE, "otp": "123456"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 2) Must return type "actual" and a token
    assert body.get("type") == "actual", body
    token = body.get("token")
    assert isinstance(token, str) and len(token) > 0

    # Some backends also return roles inline; accept either shape:
    # - roles directly on /auth/otp/verify response, OR
    # - roles fetched from /me with the token.
    roles = body.get("roles")

    if roles is None:
        # 3) If roles not returned here, fetch /me to assert roles
        r_me = client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
        assert r_me.status_code == 200, r_me.text
        me = r_me.json()
        roles = me.get("roles")

    # 4) roles must be present and contain at least the expected ones
    assert isinstance(roles, list) and len(roles) > 0, roles

    # Be lenient to your seed—assert the important ones exist
    role_names = {rb.get("role") for rb in roles if isinstance(rb, dict)}
    assert "parent" in role_names  # seeded for Asha
    # If your seed also gives Asha a vet role, this will pass; otherwise it’s optional:
    # assert "vet" in role_names
