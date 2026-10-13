# Testing this project

A guide to how the test suite is built and why, written so it doubles as an
introduction to testing in Python with pytest. Every example is real code from
this repository.

---

## 1. What tests are actually for

Three separate jobs, often confused:

| Job | Question it answers |
|---|---|
| **Verification** | Does the code do what I think it does *right now*? |
| **Regression protection** | If someone changes this in six months, will they know they broke it? |
| **Design pressure** | Is this code even reachable from the outside? Hard-to-test code is usually badly-structured code. |

The second is the one that pays for itself. A test suite is a machine that
converts "I hope I didn't break anything" into a yes/no answer in two seconds.

A test that has never failed has never proved anything. The most valuable test
in this repo is `test_burst_at_one_instant_is_counted_in_full`, because it
failed first — see section 9.

---

## 2. The shape of this suite

```
tests/
  conftest.py                  shared fixtures — the plumbing
  test_algorithm_contract.py   rules all three algorithms must obey
  test_fixed_window.py         what makes fixed window different
  test_sliding_window.py       what makes sliding window different
  test_token_bucket.py         what makes token bucket different
  test_api.py                  HTTP layer: routing, validation, response shape
  test_redis_client.py         configuration and environment wiring
```

Three layers, each catching what the layer below cannot:

**Unit tests** hand the limiter a `MagicMock` instead of Redis. They are
instant and completely deterministic, and they pin the Python arithmetic — "if
Redis says the counter is 6 and the limit is 5, the answer is `(False, 0)`".
They are also *blind to the Lua scripts*, which is where two of this project's
three algorithms keep all their logic. A suite of only unit tests here would
have been close to worthless.

**Behavioural tests** run the limiter against a working Redis implementation and
assert on observable behaviour: burst, refill, expiry, isolation between
clients. These are the tests that found real bugs.

**API tests** drive the FastAPI app through `TestClient`, covering the request
validation and response shaping that sit above the algorithms.

---

## 3. Anatomy of a test

```python
def test_a_partial_token_does_not_buy_a_request(redis_backend, clock):
    limiter = TokenBucket(redis_backend)                    # Arrange
    for _ in range(10):
        limiter.is_allowed("client", limit=10, window=10)

    clock.advance(0.5)                                      # Act

    assert limiter.is_allowed("client", limit=10, window=10)[0] is False  # Assert
```

Four things to copy:

- **Arrange / Act / Assert**, separated by blank lines. A reader should be able
  to find the one line that matters.
- **The name is a sentence about behaviour**, not about implementation.
  `test_a_partial_token_does_not_buy_a_request` tells you what broke from the
  failure output alone. `test_token_bucket_2` does not.
- **A plain `assert`.** pytest rewrites assert statements so failures show the
  actual values — no `assertEqual`, no special methods to memorise.
- **One reason to fail.** If a test can fail for three unrelated reasons, a red
  run doesn't tell you which.

---

## 4. Fixtures: setup as a dependency

A fixture is a named piece of setup that a test asks for by putting its name in
the parameter list. pytest builds it, injects it, and cleans it up.

```python
@pytest.fixture
def mock_redis():
    return MagicMock(spec=redis.Redis)
```

Anything after `yield` is teardown, and it runs even if the test fails:

```python
@pytest.fixture
def api_client(redis_backend):
    app.dependency_overrides[get_redis_client] = lambda: redis_backend
    yield TestClient(app)
    app.dependency_overrides.clear()      # always runs
```

That cleanup line matters more than it looks. `app` is a module-level singleton,
so an override left behind would leak into every later test in the session and
produce failures in files that look unrelated. **Shared mutable state is the
main source of "passes alone, fails in the suite".**

Fixtures compose — `api_client` above depends on `redis_backend`, which pytest
resolves automatically. Put fixtures in `conftest.py` and every test file in the
directory can use them without importing anything.

---

## 5. Parametrize: one test, many cases

```python
@pytest.mark.parametrize(
    "count_from_redis, expected",
    [
        (1, (True, 4)),
        (5, (True, 0)),    # exactly at the limit: still allowed
        (6, (False, 0)),   # first request over the limit
        (99, (False, 0)),  # remaining is clamped, never negative
    ],
)
def test_verdict_for_a_given_counter_value(mock_redis, count_from_redis, expected):
    mock_redis.pipeline.return_value.execute.return_value = [count_from_redis]
    assert FixedWindowCounter(mock_redis).is_allowed("user_1", 5, 60) == expected
```

Four independent tests, four separate pass/fail results, one body. Critically,
this is *not* the same as a `for` loop inside one test: with a loop, the first
failure hides the rest, and the failure message doesn't say which input broke.

The boundary cases are the point. `5` and `6` are where off-by-one errors live.
Test the edges, not the middle.

`ALGORITHMS` in `test_algorithm_contract.py` takes this further — it parametrises
over the *classes under test*, so one contract is enforced against all three
implementations, and a fourth algorithm added tomorrow inherits the suite for
free.

---

## 6. Test doubles: mock, fake, real

Three ways to stand in for a dependency, and this repo uses all three
deliberately:

| Double | Here | Good at | Blind to |
|---|---|---|---|
| **Mock** (`MagicMock`) | `mock_redis` | Asserting *how* Redis was called, and forcing exact replies | Anything Redis actually does |
| **Fake** (`fakeredis`) | `redis_backend[fakeredis]` | Real behaviour, in-process, no server | Divergence from real Redis |
| **Real** (`redis:7`) | `redis_backend[real-redis]` | The truth | Slow, needs infrastructure |

Mocks answer "did we send INCR and EXPIRE in one pipeline?" — a question about
*interaction*, which only a mock can answer:

```python
def test_increment_and_expire_are_sent_as_one_pipeline(mock_redis):
    ...
    mock_redis.pipeline.assert_called_once()
```

Fakes answer "after ten requests, is the eleventh refused?" — a question about
*state*, which a mock cannot answer at all, because a mock returns whatever you
told it to. **A mock can only confirm the beliefs you already had.** That is the
single most important thing to understand about mocking, and it is exactly why
the sliding window bug survived the original test suite: those tests asserted
that `mock_redis.eval.return_value = [1, 4]` produces `(True, 4)`, which was
true and uninteresting. The bug was inside the Lua.

`spec=redis.Redis` is worth noting — it makes the mock reject attribute names
the real client doesn't have, so a typo like `mock_redis.evla` fails loudly
instead of silently returning another mock.

### Running the same test against a fake and the real thing

```python
@pytest.fixture(params=[
    pytest.param("fake", id="fakeredis"),
    pytest.param("real", id="real-redis", marks=pytest.mark.integration),
])
def redis_backend(request):
    ...
```

Because the fixture is parametrised, **every test that requests it runs twice** —
once in-process, once against a real server. You get fake-speed feedback on a
laptop and real-Redis confidence in CI, from one set of assertions.

---

## 7. Markers: choosing what to run

```python
markers =
    integration: exercises a real Redis server; skipped when none is reachable
```

```bash
pytest -m "not integration"   # fast: fakeredis only, no server needed
pytest -m integration         # only the real-Redis pass
pytest                        # everything
```

`--strict-markers` in `pytest.ini` turns a typo'd `@pytest.mark.integraton` into
an error instead of a silently-ignored marker.

**A skipped test is not a passing test.** A suite that skips its integration
tests because Redis was misconfigured is green and meaningless, which is why
`REQUIRE_REDIS=1` exists — CI sets it, and a missing Redis becomes a red build
instead of 36 quiet skips.

---

## 8. Determinism: never sleep in a test

The tempting way to test a 60-second window is `time.sleep(61)`. Don't. It makes
the suite slow, and it makes it *flaky* — a loaded CI machine will occasionally
sleep 62 seconds and change the answer.

Instead, control the clock. All three algorithms read `time.time()` in Python
and pass the value into Redis, so one `monkeypatch` controls all of them:

```python
@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(time, "time", fake.time)
    return fake
```

```python
clock.advance(61)   # 61 seconds pass, instantly
```

`monkeypatch` is a built-in fixture that undoes every change it made when the
test ends, so the real clock is always restored. The whole suite — including
tests for ten minutes of idle token refill — runs in about two seconds.

Freezing the clock is also what *exposed* the sliding window bug, because it
guaranteed every request in a burst shared one timestamp. Determinism isn't just
about avoiding flakes; a controlled environment reproduces on demand what
production only hits occasionally.

---

## 9. Red, green, refactor — worked example from this repo

The discipline: **write a failing test first, watch it fail, then fix the code.**
The point of watching it fail is that a test you have never seen fail might not
be testing anything at all.

**Red.** The contract test said all three algorithms must allow exactly `limit`
requests. Three implementations, one shared rule:

```
FAILED test_allows_exactly_limit_requests_then_denies[fakeredis-sliding_window]
FAILED test_remaining_counts_down_to_zero[fakeredis-sliding_window]
FAILED test_clients_are_independent[fakeredis-sliding_window]
FAILED test_quota_recovers_after_the_window_passes[fakeredis-sliding_window]
4 failed, 14 passed
```

Fixed window and token bucket passed everything. The failures were perfectly
isolated to one implementation — that is the parametrised contract earning its
keep.

**Diagnosis.** The Lua used the timestamp as both the score *and the member* of
the sorted set:

```lua
redis.call('ZADD', key, now, now)
```

Sorted-set members are unique. Two requests in the same clock tick wrote the
same member, the second overwrote the first, `ZCARD` under-counted, and extra
requests sailed through. Under real Redis, network latency usually spaced
requests far enough apart to hide it — which is why the original integration
test passed. It was a load-dependent bug: fine in a demo, wrong under exactly
the traffic a rate limiter exists to handle.

**Green.** Give each request a unique member and keep the timestamp as the score:

```python
member = f"{now}:{uuid.uuid4().hex}"
```

```lua
redis.call('ZADD', key, now, member)
```

```
18 passed
```

The same loop found three more, all in the API layer: `window=0` was an
unhandled `ZeroDivisionError` (an HTTP 500 for what is plainly a bad request),
and a negative `limit` returned HTTP 200 with `remaining: -5`. Both are now
422s, enforced at the model:

```python
limit : int = Field(gt=0, description="Requests permitted per window")
window : int = Field(gt=0, description="Window length in seconds")
```

Note where that fix went. The bug appeared in two of three algorithms, but the
fix belongs in one place — the boundary where untrusted input enters. **Fix
causes, not symptoms.**

---

## 10. Coverage: useful, and easy to misread

```bash
pytest -m "not integration" --cov=app --cov-report=term-missing
```

`--cov-report=term-missing` prints the line numbers that never ran, which is the
only part of the report worth acting on. CI enforces a floor with
`--cov-fail-under=95` so coverage can't quietly rot.

What coverage measures is **which lines executed**, not whether anything was
verified. This test gets full coverage of `is_allowed` and asserts nothing:

```python
def test_useless(redis_backend):
    TokenBucket(redis_backend).is_allowed("c", 5, 60)   # covered, but not tested
```

And the sliding window had a covered, passing test suite while shipping a bug
that let unlimited requests through. **Coverage is a floor, not a score.** Low
coverage reliably indicates a problem; high coverage does not indicate its
absence. Chase uncovered lines, don't chase the percentage.

---

## 11. Running the tests

```bash
pip install -r requirements-dev.txt
```

```bash
pytest -m "not integration"            # everything that needs no server (~2s)
pytest                                 # add the real-Redis pass
pytest -v                              # one line per test, with parameter ids
pytest tests/test_token_bucket.py      # one file
pytest -k "refill"                     # every test whose name matches
pytest -x                              # stop at the first failure
pytest --lf                            # rerun only last run's failures
pytest -m "not integration" --cov=app --cov-report=term-missing
```

For the real-Redis pass:

```bash
docker run -d -p 6379:6379 redis:7
```

Without it, those tests skip. Set `REQUIRE_REDIS=1` to make a missing server an
error instead.

