from layered.copying import deep_copy


def test_nested_lists_are_copied():
    original = {"l": [{"x": 1}]}
    copy = deep_copy(original)
    copy["l"][0]["x"] = 2
    assert original == {"l": [{"x": 1}]}
