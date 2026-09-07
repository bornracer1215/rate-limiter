from pydantic import BaseModel, Field
from enum import Enum

class Algorithm(str, Enum):
    token_bucket = "token_bucket"
    sliding_window = "sliding_window"
    fixed_window = "fixed_window"

class RateLimitRequest(BaseModel):
    # `limit` and `window` must be positive. A window of 0 is a division by zero
    # in the fixed window and token bucket algorithms, and a negative limit
    # propagates straight through into a negative `remaining`. Rejecting both
    # here turns two 500s into a 422 that tells the caller what was wrong.
    client_id : str = Field(min_length=1)
    algorithm : Algorithm
    limit : int = Field(gt=0, description="Requests permitted per window")
    window : int = Field(gt=0, description="Window length in seconds")

class RateLimitResponse(BaseModel):
    allowed : bool
    remaining : int
    limit : int
    window : int
    client_id : str
