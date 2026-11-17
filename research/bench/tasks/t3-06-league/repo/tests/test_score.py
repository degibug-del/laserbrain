from league.score import parse_score


def test_multi_digit():
    assert parse_score("10-2") == (10, 2)
    assert parse_score("0-11") == (0, 11)
