import pytest

from tinytmpl import render


def test_simple():
    assert render("Hi {{name}}!", {"name": "Ana"}) == "Hi Ana!"


def test_dotted():
    assert render("{{ user.name }}", {"user": {"name": "Bo"}}) == "Bo"


def test_missing_raises():
    with pytest.raises(KeyError):
        render("{{ nope }}", {})
