import time
import redis
from .base import RateLimiter

class FixedWindowCounter(RateLimiter):
    def is_allowed(self, client_id: str, limit: int, window: int) -> tuple[bool, int]:
        key = f"fixed:{client_id}:{window}"
        current_window = int(time.time()) // window
        redis_key = f"{key}:{current_window}"

        pipe = self.redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window)
        results = pipe.execute()

        count = results[0]
        reamining = max(0, limit - count)
        allowed = count <= limit

        return allowed, reamining 