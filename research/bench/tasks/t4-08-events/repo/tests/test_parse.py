from events.parse import parse_event


def test_parse():
    assert parse_event("u1,1700000000") == ("u1", 1700000000)
