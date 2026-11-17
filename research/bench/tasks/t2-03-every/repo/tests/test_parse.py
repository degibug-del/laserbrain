import pytest

from every.parse import parse_hhmm


def test_parse():
    assert parse_hhmm("07:30") == (7, 30)


def test_out_of_range():
    with pytest.raises(ValueError):
        parse_hhmm("24:00")
