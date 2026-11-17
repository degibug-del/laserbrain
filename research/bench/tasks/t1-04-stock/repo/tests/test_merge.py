import pytest

from stock import merge


def test_sums_same_sku():
    a = [("AB-1", "3"), ("CD-2", "1,200")]
    b = [("AB-1", "2"), ("EF-3", "+5")]
    assert merge(a, b) == [("AB-1", 5), ("CD-2", 1200), ("EF-3", 5)]


def test_negative_total_raises():
    with pytest.raises(ValueError, match="AB-1"):
        merge([("AB-1", "1")], [("AB-1", "-4")])
