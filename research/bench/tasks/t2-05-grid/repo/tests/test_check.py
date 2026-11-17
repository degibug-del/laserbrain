import pytest

from grid.check import shape


def test_shape():
    assert shape([]) == (0, 0)
    assert shape([[1, 2], [3, 4]]) == (2, 2)


def test_ragged():
    with pytest.raises(ValueError):
        shape([[1, 2], [3]])
