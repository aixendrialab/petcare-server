# tests/integration/test_orgs_roles.py
from fastapi.testclient import TestClient
from tests.conftest import API, bearer

def test_add_roles_and_active_context(client: TestClient, auth_token_new):
    # add a couple of roles for a fresh user
    r = client.post(f"{API}/me/roles", headers=bearer(auth_token_new),
                    json={"roles": ["parent", "vet"]})
    assert r.status_code == 200, r.text
    roles = r.json()["roles"]
    assert any(rb["role"] == "parent" for rb in roles)
    assert any(rb["role"] == "vet" for rb in roles)

    # set active to vet, then parent
    r = client.post(f"{API}/me/active", headers=bearer(auth_token_new),
                    json={"role": "vet"})
    assert r.status_code == 200, r.text
    assert r.json()["active"]["role"] == "vet"

    r = client.post(f"{API}/me/active", headers=bearer(auth_token_new),
                    json={"role": "parent"})
    assert r.status_code == 200, r.text
    assert r.json()["active"]["role"] == "parent"
