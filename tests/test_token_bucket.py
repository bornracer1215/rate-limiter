import pytest
from app.algorithms.token_bucket import TokenBucket

def test_first_request_allowed(mock_redis):
    mock_redis.eval.return_value = [1, 4]
    
    limiter = TokenBucket(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == True
    assert remaining == 4

def test_request_denied_when_no_tokens(mock_redis):
    mock_redis.eval.return_value = [0, 0]
    
    limiter = TokenBucket(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == False
    assert remaining == 0

def test_remaining_decreases(mock_redis):
    mock_redis.eval.return_value = [1, 3]
    
    limiter = TokenBucket(mock_redis)
    allowed, remaining = limiter.is_allowed("user_1", 5, 60)
    
    assert allowed == True
    assert remaining == 3

def test_api_token_bucket(integration_client):
    for i in range(5):
        response = integration_client.post("/check", json={
            "client_id": "test_user_tb",
            "algorithm": "token_bucket",
            "limit": 5,
            "window": 60
        })
        assert response.status_code == 200
        assert response.json()["allowed"] == True

    response = integration_client.post("/check", json={
        "client_id": "test_user_tb",
        "algorithm": "token_bucket",
        "limit": 5,
        "window": 60
    })
    assert response.json()["allowed"] == False