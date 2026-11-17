from anagrams.order import stable_unique


def test_first_seen_order_with_key():
    assert stable_unique(["b", "a", "B"], key=str.lower) == ["b", "a"]
