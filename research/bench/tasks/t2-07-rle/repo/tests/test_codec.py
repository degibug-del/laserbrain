import pytest

from rle import decode, encode


def test_encode():
    assert encode("aaab") == "3a1b"
    assert encode("") == ""


def test_decode():
    assert decode("3a1b") == "aaab"


def test_round_trip():
    s = "hello  world!!"
    assert decode(encode(s)) == s


def test_digits_rejected():
    with pytest.raises(ValueError):
        encode("a1")
