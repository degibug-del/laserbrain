import pytest

from numerals import from_roman, to_roman


def test_to_roman():
    assert to_roman(1994) == "MCMXCIV"
    assert to_roman(4) == "IV"


def test_from_roman():
    assert from_roman("MCMXCIV") == 1994
    assert from_roman("xlii") == 42


def test_zero_rejected():
    with pytest.raises(ValueError):
        to_roman(0)
