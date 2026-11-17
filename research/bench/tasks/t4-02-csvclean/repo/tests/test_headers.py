from csvclean.headers import normalize_header


def test_all_spaces():
    assert normalize_header(" Ship To Address ") == "ship_to_address"
