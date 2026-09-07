# Distributed Rate Limiter Service

A standalone rate-limiting microservice supporting multiple algorithms, 
built with FastAPI and Redis.

## Algorithms
- **Token Bucket** — allows bursts, refills at a steady rate
- **Sliding Window Log** — most accurate, stores per-request timestamps
- **Fixed Window Counter** — simple and fast, resets on window boundary

## Tech Stack
Python, FastAPI, Redis, Docker, pytest, GitHub Actions, Locust

## Run with Docker
docker compose up

## API
POST /check
{
  "client_id": "user_123",
  "algorithm": "fixed_window",
  "limit": 100,
  "window": 60
}

## Run Tests
Install the test dependencies, then run the suite:

    pip install -r requirements-dev.txt
    pytest -m "not integration"

That runs all 75 non-integration cases against fakeredis in about two seconds,
with no Redis server required. To include the pass against a real Redis:

    docker run -d -p 6379:6379 redis:7
    pytest

With coverage:

    pytest -m "not integration" --cov=app --cov-report=term-missing

See [TESTING.md](TESTING.md) for how the suite is structured, what each layer
catches, and the bugs it found.

## Load Testing
locust -f locustfile.py --host http://localhost:8000