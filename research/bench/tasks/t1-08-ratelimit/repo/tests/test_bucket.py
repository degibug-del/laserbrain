from ratelimit import TokenBucket
from ratelimit.clock import FakeClock


def test_starts_full_then_denies():
    c = FakeClock()
    b = TokenBucket(rate=1, capacity=2, clock=c)
    assert [b.allow(), b.allow(), b.allow()] == [True, True, False]


def test_refills_over_time():
    c = FakeClock()
    b = TokenBucket(rate=2, capacity=2, clock=c)
    b.allow()
    b.allow()
    assert not b.allow()
    c.advance(0.5)
    assert b.allow()
    assert not b.allow()


def test_never_exceeds_capacity():
    c = FakeClock()
    b = TokenBucket(rate=10, capacity=3, clock=c)
    c.advance(100)
    assert [b.allow() for _ in range(4)] == [True, True, True, False]
