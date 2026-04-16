import pytest
from app.algorithms.sliding_window import SlidingWindowLog

def test_first_request_allowed(mock_redis):
    mock_redis.eval.return_value = [1, 4]
    
    limiter = SlidingWindowLog(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == True
    assert remaining == 4

def test_request_denied_when_full(mock_redis):
    mock_redis.eval.return_value = [0, 0]
    
    limiter = SlidingWindowLog(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == False
    assert remaining == 0

def test_remaining_counts_down(mock_redis):
    mock_redis.eval.return_value = [1, 2]
    
    limiter = SlidingWindowLog(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == True
    assert remaining == 2

def test_api_sliding_window(integration_client):
    for i in range(5):
        response = integration_client.post("/check", json={
            "client_id": "test_user_sw",
            "algorithm": "sliding_window",
            "limit": 5,
            "window": 60
        })
        assert response.status_code == 200
        assert response.json()["allowed"] == True

    response = integration_client.post("/check", json={
        "client_id": "test_user_sw",
        "algorithm": "sliding_window",
        "limit": 5,
        "window": 60
    })
    assert response.json()["allowed"] == False