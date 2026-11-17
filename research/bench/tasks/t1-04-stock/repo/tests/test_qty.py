from stock.qty import parse_qty


def test_parse_qty():
    assert parse_qty("1,200") == 1200
    assert parse_qty(" +5 ") == 5
    assert parse_qty("-3") == -3
    assert parse_qty(7) == 7
