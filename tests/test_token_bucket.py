"""Token bucket: a bucket of `limit` tokens that refills at limit/window per second.

The only algorithm of the three that permits a burst by design -- a client that
has been quiet accumulates a full bucket and may spend it all at once. These
tests pin the refill arithmetic and the capacity ceiling.
"""

import pytest

from app.algorithms.token_bucket import TokenBucket


# --------------------------------------------------------------------------
# Unit tests
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "redis_reply, expected",
    [
        ([1, 4], (True, 4)),
        ([1, 0], (True, 0)),   # spent the last token
        ([0, 0], (False, 0)),
    ],
)
def test_reply_is_unpacked_into_a_verdict(mock_redis, redis_reply, expected):
    mock_redis.eval.return_value = redis_reply

    assert TokenBucket(mock_redis).is_allowed("user_1", 5, 60) == expected


def test_refill_rate_is_limit_per_window(mock_redis):
    """A limit of 120 per 60s must be handed to Lua as 2 tokens/second."""
    mock_redis.eval.return_value = [1, 119]

    TokenBucket(mock_redis).is_allowed("user_1", 120, 60)

    refill_rate = mock_redis.eval.call_args.args[5]
    assert refill_rate == pytest.approx(2.0)


# --------------------------------------------------------------------------
# Behavioural tests
# --------------------------------------------------------------------------

def test_a_new_client_starts_with_a_full_bucket(redis_backend, clock):
    """No warm-up: an unseen client can immediately spend its whole allowance."""
    limiter = TokenBucket(redis_backend)

    verdicts = [limiter.is_allowed("new_client", limit=5, window=60)[0] for _ in range(5)]

    assert verdicts == [True] * 5
    assert limiter.is_allowed("new_client", limit=5, window=60)[0] is False


def test_tokens_return_gradually_as_time_passes(redis_backend, clock):
    """limit=10 over 10s is one token per second, so one second buys one request."""
    limiter = TokenBucket(redis_backend)
    for _ in range(10):
        limiter.is_allowed("client", limit=10, window=10)
    assert limiter.is_allowed("client", limit=10, window=10)[0] is False

    clock.advance(1)

    assert limiter.is_allowed("client", limit=10, window=10)[0] is True
    assert limiter.is_allowed("client", limit=10, window=10)[0] is False


def test_a_partial_token_does_not_buy_a_request(redis_backend, clock):
    """Half a token is not a token. Off-by-one territory: the check is `tokens >= 1`."""
    limiter = TokenBucket(redis_backend)
    for _ in range(10):
        limiter.is_allowed("client", limit=10, window=10)

    clock.advance(0.5)

    assert limiter.is_allowed("client", limit=10, window=10)[0] is False

    clock.advance(0.5)  # now a whole token has accrued

    assert limiter.is_allowed("client", limit=10, window=10)[0] is True


def test_the_bucket_does_not_fill_past_its_capacity(redis_backend, clock):
    """Idle time must not bank extra credit.

    limit=10 over 100s is 0.1 tokens/sec. One request leaves 9 tokens; 50 idle
    seconds would add 5 more, so without the `math.min(limit, ...)` ceiling the
    bucket would hold 14 and hand out 14 requests. It must cap at 10.
    """
    limiter = TokenBucket(redis_backend)
    limiter.is_allowed("client", limit=10, window=100)

    clock.advance(50)

    verdicts = [limiter.is_allowed("client", limit=10, window=100)[0] for _ in range(11)]

    assert verdicts == [True] * 10 + [False]


def test_a_long_idle_client_gets_a_full_bucket_not_more(redis_backend, clock):
    limiter = TokenBucket(redis_backend)
    for _ in range(5):
        limiter.is_allowed("client", limit=5, window=60)

    clock.advance(600)  # ten minutes idle, ten windows' worth of refill

    verdicts = [limiter.is_allowed("client", limit=5, window=60)[0] for _ in range(6)]

    assert verdicts == [True] * 5 + [False]
