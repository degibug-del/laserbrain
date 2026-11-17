from spans.pairs import as_pairs


def test_all_pairs():
    assert as_pairs([[1, 2], [3, 4]]) == [(1, 2), (3, 4)]
