from knight import distance, moves


def test_moves():
    assert moves("b1") == ["a3", "c3", "d2"]


def test_distance():
    assert distance("a1", "b3") == 1
    assert distance("e4", "e4") == 0
