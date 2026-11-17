from slugkit import slugify


def test_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_punctuation_runs_and_edges():
    assert slugify("  --Rock & Roll--  ") == "rock-roll"


def test_numbers_kept():
    assert slugify("Top 10 Tips") == "top-10-tips"


def test_max_len_word_boundary():
    assert slugify("hello big world", max_len=9) == "hello-big"
    assert slugify("hello big world", max_len=8) == "hello"


def test_no_max_len():
    assert slugify("hello big world") == "hello-big-world"
