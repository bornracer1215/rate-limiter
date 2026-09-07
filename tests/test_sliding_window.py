"""Sliding window log: a Redis sorted set of per-request timestamps.

The expensive algorithm of the three -- it stores one sorted-set member per
request -- and in exchange it is the only one with no boundary burst. These
tests cover that accuracy, and guard the duplicate-member bug that made the
whole thing under-count.
"""

import pytest

from app.algorithms.sliding_window import SlidingWindowLog


# --------------------------------------------------------------------------
# Unit tests -- the Lua script is where the logic lives, so all the Python side
# does is unpack Redis's two-element reply. Pin that.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "redis_reply, expected",
    [
        ([1, 4], (True, 4)),
        ([1, 0], (True, 0)),   # allowed, and that was the last one
        ([0, 0], (False, 0)),
    ],
)
def test_reply_is_unpacked_into_a_verdict(mock_redis, redis_reply, expected):
    mock_redis.eval.return_value = redis_reply

    assert SlidingWindowLog(mock_redis).is_allowed("user_1", 5, 60) == expected


def test_each_request_is_given_a_unique_member(mock_redis):
    """Regression guard for the collision bug.

    The member passed to ZADD used to be the timestamp itself, so two requests
    in the same clock tick overwrote each other and only counted once. The
    member must be unique per request even when the timestamps are identical.
    """
    mock_redis.eval.return_value = [1, 4]
    limiter = SlidingWindowLog(mock_redis)

    limiter.is_allowed("user_1", 5, 60)
    limiter.is_allowed("user_1", 5, 60)

    members = [call.args[-1] for call in mock_redis.eval.call_args_list]
    assert members[0] != members[1]


# --------------------------------------------------------------------------
# Behavioural tests
# --------------------------------------------------------------------------

def test_burst_at_one_instant_is_counted_in_full(redis_backend, clock):
    """Ten requests sharing a single timestamp are ten requests.

    This is the bug reproduction. With the clock frozen every request carries an
    identical timestamp; before the fix the sorted set collapsed them into one
    member and let all ten through against a limit of 3.
    """
    limiter = SlidingWindowLog(redis_backend)

    verdicts = [limiter.is_allowed("client", limit=3, window=60)[0] for _ in range(10)]

    assert verdicts == [True, True, True] + [False] * 7


def test_no_boundary_burst(redis_backend, clock):
    """The property fixed window cannot offer.

    Same scenario as test_twice_the_limit_can_pass_across_a_boundary in
    test_fixed_window.py -- quota spent, then two seconds pass. Fixed window
    hands out a second full quota; sliding window still refuses, because the
    window follows the client rather than the wall clock.
    """
    limiter = SlidingWindowLog(redis_backend)

    for _ in range(5):
        assert limiter.is_allowed("client", limit=5, window=60)[0] is True

    clock.advance(2)

    assert limiter.is_allowed("client", limit=5, window=60)[0] is False


def test_requests_age_out_one_at_a_time(redis_backend, clock):
    """Quota returns gradually, in step with the requests that used it.

    Three requests are spaced ten seconds apart. Sixty-one seconds after the
    first, exactly one slot has freed up -- not all three.
    """
    limiter = SlidingWindowLog(redis_backend)

    limiter.is_allowed("client", limit=3, window=60)
    clock.advance(10)
    limiter.is_allowed("client", limit=3, window=60)
    clock.advance(10)
    limiter.is_allowed("client", limit=3, window=60)

    assert limiter.is_allowed("client", limit=3, window=60)[0] is False

    clock.advance(41)  # 61s after the first request: it drops out of the window

    assert limiter.is_allowed("client", limit=3, window=60)[0] is True
    assert limiter.is_allowed("client", limit=3, window=60)[0] is False


def test_expired_timestamps_are_pruned_from_the_set(redis_backend, clock):
    """The set must not grow without bound -- old members are trimmed, not just ignored."""
    limiter = SlidingWindowLog(redis_backend)

    for _ in range(3):
        limiter.is_allowed("client", limit=3, window=60)
    assert redis_backend.zcard("sliding_window:client") == 3

    clock.advance(61)
    limiter.is_allowed("client", limit=3, window=60)

    assert redis_backend.zcard("sliding_window:client") == 1
