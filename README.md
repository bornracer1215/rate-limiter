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
pytest tests/ --cov=app --cov-report=term-missing

## Load Testing
locust -f locustfile.py --host http://localhost:8000