import pytest

from durations import format_duration, parse_duration


def test_parse():
    assert parse_duration("1h30m") == 5400


def test_format():
    assert format_duration(5400) == "1h30m"


def test_empty_rejected():
    with pytest.raises(ValueError):
        parse_duration("")
