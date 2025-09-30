# tests/test_pets.py
from fastapi.testclient import TestClient

API = "/api/v1"

def test_list_seed_pets_for_seed_user(client: TestClient, auth_headers):
    # Phone fixture maps to a seeded user (id=1) with 2 pets in seed.sql
    r = client.get(f"{API}/me/pets", headers=auth_headers)
    assert r.status_code == 200, r.text
    pets = r.json()["pets"]
    # Seed has Luna & Simba for user_id=1
    names = {p["name"] for p in pets}
    assert "Bruno" in names and "Misty" in names  # from seed.sql

def test_add_and_replace_pets(client: TestClient, auth_headers):
    # Add a new pet
    r = client.post(f"{API}/me/pets", headers=auth_headers, json={
        "pets": [{
            "name": "Charlie",
            "breed": "Labrador",
            "dob": "2024-01-10",
            "gender": "male",
            "vaccine_status": "up_to_date"
        }]
    })
    assert r.status_code == 200, r.text
    pets = r.json()["pets"]
    assert any(p["name"] == "Charlie" for p in pets)

    # Replace the list with a single pet
    r = client.put(f"{API}/me/pets", headers=auth_headers, json={
        "pets": [{
            "name": "Solo",
            "gender": "unknown"
        }]
    })
    assert r.status_code == 200, r.text
    pets = r.json()["pets"]
    assert len(pets) == 1
    assert pets[0]["name"] == "Solo"

    # Delete that pet
    pet_id = pets[0]["id"]
    r = client.delete(f"{API}/me/pets/{pet_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # Now list should be empty for this user
    r = client.get(f"{API}/me/pets", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["pets"] == []
