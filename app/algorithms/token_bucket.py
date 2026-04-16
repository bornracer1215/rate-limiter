import time
import redis
from .base import RateLimiter

class TokenBucket(RateLimiter):
    def is_allowed(self, client_id: str, limit: int, window: int) -> tuple[bool, int]:
        key = f"token_bucket:{client_id}"
        now = time.time()
        refill_rate = limit / window

        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        local refill_rate = tonumber(ARGV[3])
        local window = tonumber(ARGV[4])

        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1]) or limit
        local last_refill = tonumber(bucket[2]) or now

        local elapsed = now - last_refill
        tokens = math.min(limit, tokens + elapsed * refill_rate)

        local allowed = 0
        if tokens >= 1 then
            tokens = tokens - 1
            allowed = 1
        end

        redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
        redis.call('EXPIRE', key, window)

        return {allowed, math.floor(tokens)}
        """

        result = self.redis.eval(lua_script, 1, key, now, limit, refill_rate, window)
        allowed = result[0] == 1
        remaining = int(result[1])

        return allowed, remaining