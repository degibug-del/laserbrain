from datetime import timedelta

from flights.tz import parse_offset


def test_offsets():
    assert parse_offset("+05:30") == timedelta(hours=5, minutes=30)
    assert parse_offset("-04:00") == timedelta(hours=-4)
