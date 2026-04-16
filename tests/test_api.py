import pytest

def test_health_check(test_client):
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_invalid_algorithm(test_client):
    response = test_client.post("/check", json={
        "client_id": "user_1",
        "algorithm": "invalid_algorithm",
        "limit": 5,
        "window": 60
    })
    assert response.status_code == 422

def test_missing_client_id(test_client):
    response = test_client.post("/check", json={
        "algorithm": "fixed_window",
        "limit": 5,
        "window": 60
    })
    assert response.status_code == 422

def test_missing_limit(test_client):
    response = test_client.post("/check", json={
        "client_id": "user_1",
        "algorithm": "fixed_window",
        "window": 60
    })
    assert response.status_code == 422

def test_response_shape(integration_client):
    response = integration_client.post("/check", json={
        "client_id": "user_shape_test",
        "algorithm": "fixed_window",
        "limit": 10,
        "window": 60
    })
    assert response.status_code == 200
    data = response.json()
    assert "allowed" in data
    assert "remaining" in data
    assert "limit" in data
    assert "window" in data
    assert "client_id" in data
    assert data["client_id"] == "user_shape_test"
    assert data["limit"] == 10
    assert data["window"] == 60