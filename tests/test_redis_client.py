"""Connection configuration.

Small surface, but it is the seam between the app and its environment: a
mistake here means the service silently talks to localhost in production. Note
that `redis.Redis(...)` does not open a socket, so these tests can inspect the
resulting configuration without a server anywhere.
"""

from app.redis_client import get_redis_client


def connection_kwargs(client):
    return client.connection_pool.connection_kwargs


def test_defaults_to_localhost_6379(monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    monkeypatch.delenv("REDIS_PORT", raising=False)

    kwargs = connection_kwargs(get_redis_client())

    assert kwargs["host"] == "localhost"
    assert kwargs["port"] == 6379


def test_host_and_port_come_from_the_environment(monkeypatch):
    """docker-compose sets REDIS_HOST=redis; this is the mechanism that reads it."""
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6380")

    kwargs = connection_kwargs(get_redis_client())

    assert kwargs["host"] == "redis"
    assert kwargs["port"] == 6380


def test_port_is_coerced_to_an_int(monkeypatch):
    """Environment variables are strings; a string port breaks the socket call."""
    monkeypatch.setenv("REDIS_PORT", "6380")

    assert isinstance(connection_kwargs(get_redis_client())["port"], int)


def test_responses_are_decoded_to_str(monkeypatch):
    """decode_responses=False would make every Lua reply and key a bytes object,
    and the f-string keys the algorithms build would stop matching."""
    assert connection_kwargs(get_redis_client())["decode_responses"] is True
