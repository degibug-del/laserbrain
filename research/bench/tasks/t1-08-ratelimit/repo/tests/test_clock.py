from ratelimit.clock import FakeClock


def test_advance_accumulates():
    c = FakeClock()
    c.advance(1)
    c.advance(2)
    assert c() == 3.0
