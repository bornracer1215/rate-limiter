"""Contract tests: the rules every algorithm must obey, regardless of how it works.

Token bucket, sliding window log and fixed window counter are three different
mechanisms, but they all promise the same thing to a caller: allow `limit`
requests, then start refusing. Writing that promise once and parametrising over
the implementations means a fourth algorithm added tomorrow inherits the whole
suite for free -- and it is how the sliding-window collision bug was caught,
because only one of the three implementations broke the shared rule.
"""

import pytest

from app.algorithms.fixed_window import FixedWindowCounter
from app.algorithms.sliding_window import SlidingWindowLog
from app.algorithms.token_bucket import TokenBucket

# One place to list the implementations. `ids` give readable test names like
# test_allows_exactly_limit_requests[token_bucket-fakeredis].
ALGORITHMS = [
    pytest.param(FixedWindowCounter, id="fixed_window"),
    pytest.param(SlidingWindowLog, id="sliding_window"),
    pytest.param(TokenBucket, id="token_bucket"),
]


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_allows_exactly_limit_requests_then_denies(algorithm, redis_backend, clock):
    """The core promise: `limit` requests through, request `limit + 1` refused.

    The clock is frozen, so every request in this burst carries an identical
    timestamp. That is a normal thing for a fast client to do, and it is what
    exposed the sliding window's duplicate-member bug.
    """
    limiter = algorithm(redis_backend)

    for i in range(5):
        allowed, _ = limiter.is_allowed("client", limit=5, window=60)
        assert allowed is True, f"request {i + 1} of 5 should have been allowed"

    allowed, _ = limiter.is_allowed("client", limit=5, window=60)
    assert allowed is False, "the 6th request exceeded a limit of 5"


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_remaining_counts_down_to_zero(algorithm, redis_backend, clock):
    """`remaining` decreases by one per request and bottoms out at zero."""
    limiter = algorithm(redis_backend)

    seen = [limiter.is_allowed("client", limit=3, window=60)[1] for _ in range(3)]

    assert seen == [2, 1, 0]


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_remaining_never_goes_negative(algorithm, redis_backend, clock):
    """Refused requests must not report a negative allowance."""
    limiter = algorithm(redis_backend)

    for _ in range(10):
        _, remaining = limiter.is_allowed("client", limit=2, window=60)
        assert remaining >= 0


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_clients_are_independent(algorithm, redis_backend, clock):
    """One client exhausting its quota must not affect another."""
    limiter = algorithm(redis_backend)

    for _ in range(3):
        limiter.is_allowed("noisy_client", limit=3, window=60)
    assert limiter.is_allowed("noisy_client", limit=3, window=60)[0] is False

    allowed, remaining = limiter.is_allowed("quiet_client", limit=3, window=60)
    assert allowed is True
    assert remaining == 2


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_limit_of_one(algorithm, redis_backend, clock):
    """A limit of 1 is the tightest useful setting -- an easy off-by-one to get wrong."""
    limiter = algorithm(redis_backend)

    assert limiter.is_allowed("client", limit=1, window=60) == (True, 0)
    assert limiter.is_allowed("client", limit=1, window=60)[0] is False


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_quota_recovers_after_the_window_passes(algorithm, redis_backend, clock):
    """Whatever the mechanism, a client blocked now must be servable later.

    This is the one shared rule that needs the clock crank: exhaust the quota,
    push time past the window, and check the client is served again.
    """
    limiter = algorithm(redis_backend)

    for _ in range(2):
        limiter.is_allowed("client", limit=2, window=60)
    assert limiter.is_allowed("client", limit=2, window=60)[0] is False

    clock.advance(61)

    assert limiter.is_allowed("client", limit=2, window=60)[0] is True
