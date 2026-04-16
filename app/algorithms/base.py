from abc import ABC, abstractmethod
import redis

class RateLimiter(ABC):
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    @abstractmethod
    def is_allowed(self, client_id: str, limit: int, window: int) -> tuple[bool, int]:
        pass