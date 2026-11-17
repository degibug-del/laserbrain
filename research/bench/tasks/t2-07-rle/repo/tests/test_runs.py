from rle.runs import runs


def test_runs():
    assert runs("aaab") == [("a", 3), ("b", 1)]
    assert runs("") == []
