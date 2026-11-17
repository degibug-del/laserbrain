from spans import merge


def test_overlapping():
    assert merge([[1, 4], [2, 6], [8, 10]]) == [[1, 6], [8, 10]]


def test_unsorted():
    assert merge([[8, 10], [1, 3]]) == [[1, 3], [8, 10]]
