from wordfreq.tokenize import split_words


def test_split_words():
    assert split_words("Hello, world! It's 'fine'") == ["hello", "world", "it's", "fine"]
