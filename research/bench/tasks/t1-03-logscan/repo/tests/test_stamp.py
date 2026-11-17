import pytest

from logscan.stamp import parse_ts


def test_parses_iso():
    assert parse_ts("2026-10-01T12:34:56").minute == 34


def test_rejects_garbage():
    with pytest.raises(ValueError):
        parse_ts("yesterday")
