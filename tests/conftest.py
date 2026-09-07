"""Shared pytest fixtures for the rate limiter test suite.

Three kinds of test live here, and they catch different kinds of bug:

1. Unit tests -- the limiter is handed a MagicMock instead of Redis. They assert
   on how the class turns a Redis reply into (allowed, remaining). Fast, fully
   deterministic, but blind to anything that happens inside the Lua scripts.

2. Behavioural tests -- the limiter talks to a real Redis *implementation*. The
   `redis_backend` fixture runs every one of these twice: once against fakeredis
   (in-process, always available) and once against a real Redis server (skipped
   when none is reachable). These are the tests that catch Lua bugs.

3. API tests -- the FastAPI app is driven through TestClient, so request
   validation and response shaping are covered as well.
"""

import os
import socket
import time
from unittest.mock import MagicMock

import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

from app.main import app
from app.redis_client import get_redis_client


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

@pytest.fixture
def mock_redis():
    """A Redis stand-in that records calls and returns whatever we tell it to.

    `spec=redis.Redis` makes the mock reject attribute names that the real
    client does not have, so a typo like `mock_redis.evla` fails loudly instead
    of silently returning another mock.
    """
    return MagicMock(spec=redis.Redis)


# A dropped packet (rather than a refused connection) makes redis-py's retry
# loop hang for a long time, which would stall the suite on any machine with a
# firewall in the way. A raw socket probe settles reachability in half a second.
# The result is cached because it cannot change during a run.
_redis_reachable = None


def _redis_port_is_open(host, port, timeout=0.5):
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def _real_redis_or_skip():
    """Connect to a real Redis, or skip the test if one is not running.

    Set REQUIRE_REDIS=1 to turn that skip into a failure. CI sets it for the
    integration job, so a broken Redis service reports as a red build instead of
    a green one where every integration test quietly skipped.
    """
    global _redis_reachable

    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", 6379))

    if _redis_reachable is None:
        _redis_reachable = _redis_port_is_open(host, port)

    if not _redis_reachable:
        message = f"no Redis server listening on {host}:{port}"
        if os.getenv("REQUIRE_REDIS") == "1":
            pytest.fail(f"REQUIRE_REDIS=1 but {message}")
        pytest.skip(message)

    return redis.Redis(
        host=host,
        port=port,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


@pytest.fixture(
    params=[
        pytest.param("fake", id="fakeredis"),
        pytest.param("real", id="real-redis", marks=pytest.mark.integration),
    ]
)
def redis_backend(request):
    """A working Redis, parametrised over fakeredis and a real server.

    Every test that requests this fixture runs twice. `-m "not integration"`
    keeps only the fakeredis pass, which is what makes the suite runnable on a
    laptop with no Redis installed. CI runs both.
    """
    if request.param == "fake":
        client = fakeredis.FakeStrictRedis(decode_responses=True)
        yield client
        client.flushall()
    else:
        client = _real_redis_or_skip()
        client.flushdb()
        yield client
        client.flushdb()


# --------------------------------------------------------------------------
# API clients
# --------------------------------------------------------------------------

@pytest.fixture
def test_client(mock_redis):
    """TestClient wired to the mock. For tests that never reach Redis."""
    app.dependency_overrides[get_redis_client] = lambda: mock_redis
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def api_client(redis_backend):
    """TestClient wired to a working Redis, parametrised like `redis_backend`.

    FastAPI's `dependency_overrides` is the seam that makes this possible: the
    endpoint asks for its Redis via `Depends(get_redis_client)`, so a test can
    swap in any client without the application code knowing.
    """
    app.dependency_overrides[get_redis_client] = lambda: redis_backend
    yield TestClient(app)
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Time control
# --------------------------------------------------------------------------

class FakeClock:
    """A hand-cranked replacement for the system clock.

    All three algorithms read `time.time()` in Python and pass the value into
    Redis, so controlling this one function is enough to control what the
    limiters believe the time is -- no `sleep()` needed anywhere in the suite.
    """

    def __init__(self, start=1_700_000_000.0):
        self.now = start

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


@pytest.fixture
def clock(monkeypatch):
    """Freeze `time.time()` and hand the test the crank."""
    fake = FakeClock()
    monkeypatch.setattr(time, "time", fake.time)
    return fake
