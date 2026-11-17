from datetime import date

from library.dates import parse_date


def test_iso():
    assert parse_date("2026-10-01") == date(2026, 10, 1)
