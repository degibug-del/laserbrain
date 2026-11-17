from slugkit._text import collapse


def test_collapse_runs():
    assert collapse("a---b", "-") == "a-b"
    assert collapse("a--b----c", "-") == "a-b-c"
    assert collapse("abc", "-") == "abc"
