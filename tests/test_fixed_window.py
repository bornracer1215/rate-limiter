import pytest
from unittest.mock import MagicMock, patch
from app.algorithms.fixed_window import FixedWindowCounter

def test_first_request_allowed(mock_redis):
    mock_redis.pipeline.return_value.__enter__ = MagicMock()
    mock_redis.pipeline.return_value.__exit__ = MagicMock()
    mock_redis.pipeline.return_value.execute.return_value = [1]
    
    limiter = FixedWindowCounter(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == True
    assert remaining == 4

def test_request_at_limit(mock_redis):
    mock_redis.pipeline.return_value.execute.return_value = [5]
    
    limiter = FixedWindowCounter(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == True
    assert remaining == 0

def test_request_over_limit(mock_redis):
    mock_redis.pipeline.return_value.execute.return_value = [6]
    
    limiter = FixedWindowCounter(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == False
    assert remaining == 0

def test_different_clients_independent(mock_redis):
    mock_redis.pipeline.return_value.execute.return_value = [1]
    
    limiter = FixedWindowCounter(mock_redis)
    allowed_1, _ = limiter.is_allowed("user_1", 5, 60)
    allowed_2, _ = limiter.is_allowed("user_2", 5, 60)
    
    assert allowed_1 == True
    assert allowed_2 == True

def test_api_fixed_window(integration_client):
    for i in range(5):
        response = integration_client.post("/check", json={
            "client_id": "test_user",
            "algorithm": "fixed_window",
            "limit": 5,
            "window": 60
        })
        assert response.status_code == 200
        assert response.json()["allowed"] == True

    response = integration_client.post("/check", json={
        "client_id": "test_user",
        "algorithm": "fixed_window",
        "limit": 5,
        "window": 60
    })
    assert response.json()["allowed"] == False