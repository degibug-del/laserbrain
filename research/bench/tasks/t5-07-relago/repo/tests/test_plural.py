from relago.plural import plural


def test_plural():
    assert plural(1, "minute") == "1 minute"
    assert plural(2, "day") == "2 days"
