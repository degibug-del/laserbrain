import time


class TokenBucket:
    """Token-bucket rate limiter. See the task description."""

    def __init__(self, rate, capacity, clock=time.monotonic):
        raise NotImplementedError
