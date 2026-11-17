from handles import validate


def test_ok():
    assert validate("ok_name") == []


def test_length():
    assert validate("ab") == ["length"]
    assert validate("a" * 21) == ["length"]


def test_chars():
    assert validate("Bad!") == ["chars"]


def test_leading_digit():
    assert validate("9lives") == ["leading_digit"]
