from wraptext import wrap


def test_greedy():
    assert wrap("the quick brown fox", 10) == ["the quick", "brown fox"]


def test_extra_spaces():
    assert wrap("a   b", 10) == ["a b"]
