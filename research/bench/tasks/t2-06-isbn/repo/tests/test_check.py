from isbn import is_valid, to_isbn13


def test_valid_10_and_13():
    assert is_valid("0-306-40615-2")
    assert is_valid("978-0-306-40615-7")


def test_bad_check_digit():
    assert not is_valid("0-306-40615-3")


def test_convert():
    assert to_isbn13("0306406152") == "9780306406157"
