from csvline import split_line


def test_plain():
    assert split_line("a,b,c") == ["a", "b", "c"]


def test_quoted_comma():
    assert split_line('"x, y",z') == ["x, y", "z"]


def test_escaped_quote():
    assert split_line('"say ""hi""",ok') == ['say "hi"', "ok"]


def test_empty_middle():
    assert split_line("a,,b") == ["a", "", "b"]
