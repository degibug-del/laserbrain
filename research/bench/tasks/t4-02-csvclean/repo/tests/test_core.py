from csvclean import clean_rows


def test_clean():
    rows = [["Name ", "Unit Price"], [" tea ", "4.50"], ["", ""], ["coffee", " "]]
    assert clean_rows(rows) == [
        {"name": "tea", "unit_price": "4.50"},
        {"name": "coffee", "unit_price": None},
    ]
