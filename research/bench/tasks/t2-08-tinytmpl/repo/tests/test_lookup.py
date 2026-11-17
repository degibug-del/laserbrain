import pytest

from tinytmpl.lookup import resolve


def test_nested():
    assert resolve({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_missing():
    with pytest.raises(KeyError):
        resolve({"a": {}}, "a.b")
