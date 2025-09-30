# tests/test_orgs_roles.py
from fastapi.testclient import TestClient

API = "/api/v1"

def test_add_roles_and_active_context(client: TestClient, auth_headers):
    # add a couple of roles
    r = client.post(f"{API}/me/roles", headers=auth_headers,
                    json={"roles": ["parent", "vet"]})
    assert r.status_code == 200, r.text
    roles = r.json()["roles"]
    assert any(rb["role"] == "parent" for rb in roles)
    assert any(rb["role"] == "vet" for rb in roles)

    # switch active to vet @ org
    r = client.post(f"{API}/me/active", headers=auth_headers,
                    json={"role": "vet"})
    assert r.status_code == 200, r.text
    active = r.json()["active"]
    assert active["role"] == "vet"

    # set active context to parent (no org)
    r = client.post(f"{API}/me/active", headers=auth_headers,
                    json={"role": "parent"})
    assert r.status_code == 200, r.text
    active = r.json()["active"]
    assert active["role"] == "parent"
    assert active.get("org") is None