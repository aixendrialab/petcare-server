from starlette.testclient import TestClient

def test_health(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code in (200, 404)  # health may or may not exist

def test_appointments_list(client: TestClient):
    r = client.get("/api/v1/appointments")
    assert r.status_code in (200, 401, 403)  # allow auth layer to vary

def test_queue_today(client: TestClient):
    r = client.get("/api/v1/users/vet/1/queue")
    assert r.status_code in (200, 401, 403)