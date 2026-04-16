from pydantic import BaseModel
from enum import Enum

class Algorithm(str, Enum):
    token_bucket = "token_bucket"
    sliding_window = "sliding_window"
    fixed_window = "fixed_window"

class RateLimitRequest(BaseModel):
    client_id : str
    algorithm : Algorithm
    limit : int
    window : int

class RateLimitResponse(BaseModel):
    allowed : bool
    remaining : int
    limit : int
    window : int
    client_id : str

    