import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
import redis
from app.main import app
from app.redis_client import get_redis_client

@pytest.fixture
def mock_redis():
    return MagicMock(spec=redis.Redis)

@pytest.fixture
def real_redis():
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    yield client
    client.flushdb()

@pytest.fixture
def test_client(mock_redis):
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def integration_client(real_redis):
    app.dependency_overrides[get_redis_client] = lambda: real_redis
    yield TestClient(app)
    app.dependency_overrides.clear()

    