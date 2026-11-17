from numstats import median, mode


def test_median():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5


def test_mode():
    assert mode([1, 2, 2, 3]) == 2
    assert mode([3, 3, 1, 1]) == 1
