from csvline.chars import is_quote


def test_double_quote():
    assert is_quote('"') and not is_quote("'")
