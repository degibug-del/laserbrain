from pager.mathx import ceil_div


def test_ceil_div():
    assert ceil_div(7, 3) == 3
    assert ceil_div(6, 3) == 2
