from layered import merge


def test_nested_merge():
    assert merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3}}) == {"a": {"x": 1, "y": 3}, "b": 1}


def test_lists_replace():
    assert merge({"l": [1, 2]}, {"l": [3]}) == {"l": [3]}


def test_none_deletes():
    assert merge({"a": 1, "b": 2}, {"b": None}) == {"a": 1}
