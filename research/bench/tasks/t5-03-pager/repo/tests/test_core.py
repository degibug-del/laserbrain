import pytest

from pager import paginate

ITEMS = list(range(25))


def test_last_page():
    assert paginate(ITEMS, 3, 10) == {
        "items": [20, 21, 22, 23, 24], "page": 3, "pages": 3, "has_next": False, "has_prev": True}


def test_first_page():
    out = paginate(ITEMS, 1, 10)
    assert out["items"] == list(range(10)) and out["has_next"] and not out["has_prev"]


def test_page_past_end():
    with pytest.raises(ValueError):
        paginate(ITEMS, 4, 10)
