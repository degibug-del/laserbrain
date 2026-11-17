from slots.hhmm import from_minutes, to_minutes


def test_round_trip():
    assert to_minutes("09:05") == 545
    assert from_minutes(545) == "09:05"
