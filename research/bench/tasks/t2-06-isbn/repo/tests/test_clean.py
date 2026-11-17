from isbn.clean import normalize


def test_normalize():
    assert normalize("0 306-40615 2") == "0306406152"
    assert normalize("080442957x") == "080442957X"
