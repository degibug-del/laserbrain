from wraptext.words import split_words


def test_runs_of_spaces():
    assert split_words("a  b   c") == ["a", "b", "c"]
