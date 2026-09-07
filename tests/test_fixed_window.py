"""Fixed window counter: one Redis counter per (client, window) bucket.

The contract tests already cover what this algorithm shares with the other two.
What is left here is the behaviour specific to bucketing time into fixed slots
-- including the boundary burst, which is this algorithm's well-known weakness
and is pinned deliberately so nobody "fixes" it by accident.
"""


import pytest

from app.algorithms.fixed_window import FixedWindowCounter


def align_just_before_boundary(clock, window):
    """Move the clock to one second before a window boundary."""
    clock.now = float((int(clock.now) // window + 1) * window - 1)


# --------------------------------------------------------------------------
# Unit tests -- Redis replaced by a mock, so only the Python arithmetic is under
# test. These pin the translation from "Redis says the counter is N" to
# "(allowed, remaining)".
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "count_from_redis, expected",
    [
        (1, (True, 4)),    # first request of the window
        (4, (True, 1)),
        (5, (True, 0)),    # exactly at the limit: still allowed
        (6, (False, 0)),   # first request over the limit
        (99, (False, 0)),  # remaining is clamped, never negative
    ],
)
def test_verdict_for_a_given_counter_value(mock_redis, count_from_redis, expected):
    mock_redis.pipeline.return_value.execute.return_value = [count_from_redis]

    limiter = FixedWindowCounter(mock_redis)

    assert limiter.is_allowed("user_1", 5, 60) == expected


def test_counter_is_incremented_and_given_a_ttl(mock_redis):
    """Every call must set an expiry, or abandoned buckets accumulate in Redis forever."""
    pipeline = mock_redis.pipeline.return_value
    pipeline.execute.return_value = [1]

    FixedWindowCounter(mock_redis).is_allowed("user_1", 5, 60)

    assert pipeline.incr.called
    pipeline.expire.assert_called_once()
    assert pipeline.expire.call_args[0][1] == 60


def test_increment_and_expire_are_sent_as_one_pipeline(mock_redis):
    """INCR and EXPIRE must travel together.

    Sent separately, a crash between them leaves a counter with no TTL, which
    would block that client until someone deletes the key by hand.
    """
    pipeline = mock_redis.pipeline.return_value
    pipeline.execute.return_value = [1]

    FixedWindowCounter(mock_redis).is_allowed("user_1", 5, 60)

    mock_redis.pipeline.assert_called_once()
    pipeline.execute.assert_called_once()


# --------------------------------------------------------------------------
# Behavioural tests -- run against fakeredis and, in CI, a real Redis server.
# --------------------------------------------------------------------------

def test_counter_resets_when_the_window_rolls_over(redis_backend, clock):
    limiter = FixedWindowCounter(redis_backend)

    for _ in range(3):
        limiter.is_allowed("client", limit=3, window=60)
    assert limiter.is_allowed("client", limit=3, window=60)[0] is False

    clock.advance(60)

    assert limiter.is_allowed("client", limit=3, window=60) == (True, 2)


def test_twice_the_limit_can_pass_across_a_boundary(redis_backend, clock):
    """The fixed window's known flaw, pinned as documented behaviour.

    A client that spends its whole quota at the end of one window and its whole
    quota at the start of the next gets 2x the limit in a very short span. This
    is the accepted price of the algorithm's simplicity -- sliding window exists
    precisely to avoid it (see test_sliding_window.py for the contrast).
    """
    limiter = FixedWindowCounter(redis_backend)
    align_just_before_boundary(clock, window=60)

    for _ in range(5):
        assert limiter.is_allowed("client", limit=5, window=60)[0] is True

    clock.advance(2)  # two seconds later, but a new window

    for _ in range(5):
        assert limiter.is_allowed("client", limit=5, window=60)[0] is True


def test_different_window_sizes_are_counted_separately(redis_backend, clock):
    """A 60s quota and a 3600s quota for the same client must not share a counter."""
    limiter = FixedWindowCounter(redis_backend)

    for _ in range(2):
        limiter.is_allowed("client", limit=2, window=60)
    assert limiter.is_allowed("client", limit=2, window=60)[0] is False

    assert limiter.is_allowed("client", limit=2, window=3600)[0] is True


def test_key_carries_a_ttl_in_redis(redis_backend, clock):
    """Check the expiry actually landed, not just that expire() was called."""
    FixedWindowCounter(redis_backend).is_allowed("ttl_client", limit=5, window=60)

    key = next(iter(redis_backend.scan_iter(match="fixed:ttl_client:*")))
    assert 0 < redis_backend.ttl(key) <= 60
