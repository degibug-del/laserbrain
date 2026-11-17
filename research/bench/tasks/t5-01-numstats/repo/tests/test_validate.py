from numstats.validate import ensure_numbers


def test_ints_and_floats():
    assert ensure_numbers([1, 2.5]) == [1, 2.5]
