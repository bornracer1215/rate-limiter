from fastapi import FastAPI, Depends
import redis as redis_lib
from .models import RateLimitRequest, RateLimitResponse
from .redis_client import get_redis_client
from .algorithms.fixed_window import FixedWindowCounter
from .algorithms.sliding_window import SlidingWindowLog
from .algorithms.token_bucket import TokenBucket

app = FastAPI(title="Rate Limiter Service")

def get_limiter(algorithm: str, redis_client: redis_lib.Redis):
    if algorithm == "fixed_window":
        return FixedWindowCounter(redis_client)
    elif algorithm == "sliding_window":
        return SlidingWindowLog(redis_client)
    elif algorithm == "token_bucket":
        return TokenBucket(redis_client)
    raise ValueError("Invalid algorithm")

@app.post("/check", response_model=RateLimitResponse)

def check_rate_limit(request: RateLimitRequest, redis_client: redis_lib.Redis = Depends(get_redis_client)):
    limiter = get_limiter(request.algorithm, redis_client)
    allowed, remaining = limiter.is_allowed(request.client_id, request.limit, request.window)

    return RateLimitResponse(
        allowed=allowed,
        remaining=remaining,
        limit=request.limit,
        window=request.window,
        client_id=request.client_id
    )
    
@app.get("/health")
def health():
    return {"status": "ok"}