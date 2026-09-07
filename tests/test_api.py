"""Tests for the HTTP layer: routing, request validation, response shape.

These stop at the edge of the application. Whether the *algorithms* are correct
is settled in test_algorithm_contract.py and the per-algorithm files; what is
being checked here is that a caller who sends nonsense gets a clear 422 instead
of a 500, and that a caller who sends something valid gets the documented shape
back.
"""

import pytest

from app.algorithms.fixed_window import FixedWindowCounter
from app.algorithms.sliding_window import SlidingWindowLog
from app.algorithms.token_bucket import TokenBucket
from app.main import get_limiter

VALID_REQUEST = {
    "client_id": "user_1",
    "algorithm": "fixed_window",
    "limit": 5,
    "window": 60,
}


def request_body(**overrides):
    """A valid request with specific fields changed, so each test shows only its variable."""
    return {**VALID_REQUEST, **overrides}


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------

def test_health_check(test_client):
    response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --------------------------------------------------------------------------
# Request validation
#
# Everything here should be rejected by pydantic *before* any Redis call is
# made. The client is wired to a mock, so if a request slips through validation
# and reaches the limiter, the test fails loudly rather than quietly passing.
# --------------------------------------------------------------------------

def test_unknown_algorithm_is_rejected(test_client):
    response = test_client.post("/check", json=request_body(algorithm="mystery_algorithm"))

    assert response.status_code == 422


@pytest.mark.parametrize("missing_field", ["client_id", "algorithm", "limit", "window"])
def test_missing_required_field_is_rejected(test_client, missing_field):
    body = request_body()
    del body[missing_field]

    response = test_client.post("/check", json=body)

    assert response.status_code == 422
    assert missing_field in response.text


@pytest.mark.parametrize(
    "field, value",
    [
        ("limit", "not_a_number"),
        ("window", "not_a_number"),
        ("client_id", 12345),
        ("limit", 1.5),
    ],
    ids=["limit-string", "window-string", "client_id-int", "limit-float"],
)
def test_wrong_type_is_rejected(test_client, field, value):
    response = test_client.post("/check", json=request_body(**{field: value}))

    assert response.status_code == 422


@pytest.mark.parametrize("bad_window", [0, -1, -60])
def test_non_positive_window_is_rejected(test_client, bad_window):
    """A window of zero is a division by zero in two of the three algorithms.

    Before this was validated, `window=0` produced an unhandled ZeroDivisionError
    -- a 500 and a stack trace in the logs for what is really a bad request.
    """
    response = test_client.post("/check", json=request_body(window=bad_window))

    assert response.status_code == 422


@pytest.mark.parametrize("bad_limit", [0, -1, -5])
def test_non_positive_limit_is_rejected(test_client, bad_limit):
    """A negative limit used to leak straight through into a negative `remaining`.

    `limit=-5` returned HTTP 200 with `remaining: -5`, which no caller can do
    anything sensible with.
    """
    response = test_client.post("/check", json=request_body(limit=bad_limit))

    assert response.status_code == 422


# --------------------------------------------------------------------------
# Response shape
# --------------------------------------------------------------------------

def test_response_echoes_the_request_parameters(api_client):
    response = api_client.post("/check", json=request_body(client_id="user_shape_test", limit=10))

    assert response.status_code == 200
    assert response.json() == {
        "allowed": True,
        "remaining": 9,
        "limit": 10,
        "window": 60,
        "client_id": "user_shape_test",
    }


def test_denied_request_still_returns_200(api_client):
    """A refusal is a successful answer to the question, not an HTTP error.

    /check reports a verdict; it does not proxy the request. Callers read
    `allowed`, so returning 429 here would be wrong. Pinned deliberately.
    """
    for _ in range(2):
        api_client.post("/check", json=request_body(limit=2))

    response = api_client.post("/check", json=request_body(limit=2))

    assert response.status_code == 200
    assert response.json()["allowed"] is False


# --------------------------------------------------------------------------
# Algorithm selection
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, expected_class",
    [
        ("fixed_window", FixedWindowCounter),
        ("sliding_window", SlidingWindowLog),
        ("token_bucket", TokenBucket),
    ],
)
def test_get_limiter_builds_the_right_class(name, expected_class, mock_redis):
    assert isinstance(get_limiter(name, mock_redis), expected_class)


def test_get_limiter_rejects_an_unknown_name(mock_redis):
    """Unreachable through the API -- the enum catches it first -- but the guard
    still has to hold for anyone calling get_limiter() directly."""
    with pytest.raises(ValueError):
        get_limiter("mystery_algorithm", mock_redis)


@pytest.mark.parametrize("algorithm", ["fixed_window", "sliding_window", "token_bucket"])
def test_every_algorithm_is_reachable_end_to_end(api_client, algorithm):
    """Each enum value survives the whole round trip: HTTP -> limiter -> Redis -> HTTP."""
    response = api_client.post("/check", json=request_body(algorithm=algorithm, limit=3))

    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["remaining"] == 2
