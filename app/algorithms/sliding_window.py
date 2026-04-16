import time
import redis
from .base import RateLimiter

class SlidingWindowLog(RateLimiter):
    def is_allowed(self, client_id: str, limit: int, window: int) -> tuple[bool, int]:
        key = f"sliding_window:{client_id}"
        now = time.time()
        window_start = now-window

        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local limit = tonumber(ARGV[3])
        local window = tonumber(ARGV[4])
        
        redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
        
        local count = redis.call('ZCARD', key)
        
        local allowed = 0
        if count < limit then
            redis.call('ZADD', key, now, now)
            allowed = 1
            count = count + 1 
        end
        
        redis.call ('EXPIRE', key, window)
        
        return {allowed, limit-count}
        """

        result = self.redis.eval(lua_script, 1, key, now, window_start, limit, window)
        allowed = result[0] == 1
        remaining = int(result[1])

        return allowed, remaining