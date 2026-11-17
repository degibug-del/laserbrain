import time


class TokenBucket:
    def __init__(self, rate, capacity, clock=time.monotonic):
        self.rate = float(rate)
        self.capacity = float(capacity)
        self.clock = clock
        self.tokens = float(capacity)
        self.last = clock()

    def _refill(self):
        now = self.clock()
        elapsed = max(0.0, now - self.last)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last = now

    def allow(self):
        self._refill()
        if self.tokens + 1e-9 >= 1:
            self.tokens -= 1
            return True
        return False

    def wait_time(self, cost=1):
        if cost > self.capacity:
            raise ValueError("cost exceeds capacity")
        self._refill()
        missing = cost - self.tokens
        return 0.0 if missing <= 1e-9 else missing / self.rate
