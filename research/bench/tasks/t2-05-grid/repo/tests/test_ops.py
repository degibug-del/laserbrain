import pytest

from grid import rotate, transpose


def test_transpose():
    assert transpose([[1, 2, 3], [4, 5, 6]]) == [[1, 4], [2, 5], [3, 6]]


def test_rotate_clockwise():
    assert rotate([[1, 2], [3, 4]]) == [[3, 1], [4, 2]]


def test_ragged_rejected():
    with pytest.raises(ValueError):
        transpose([[1, 2], [3]])
