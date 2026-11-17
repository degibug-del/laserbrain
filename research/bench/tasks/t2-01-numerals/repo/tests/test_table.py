from numerals.table import PAIRS


def test_values():
    values = dict(PAIRS)
    assert values["CM"] == 900
    assert values["XL"] == 40
    assert [v for _, v in PAIRS] == sorted((v for _, v in PAIRS), reverse=True)
