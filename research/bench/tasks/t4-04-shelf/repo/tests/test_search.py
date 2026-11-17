from shelf import search

BOOKS = [
    {"title": "Jane Eyre", "author": "Charlotte Brontë", "year": 1847},
    {"title": "Emma", "author": "Jane Austen", "year": 1815},
    {"title": "Persuasion", "author": "Jane Austen", "year": 1817},
    {"title": "Wuthering Heights", "author": "Emily Brontë", "year": 1847},
]


def titles(found):
    return [b["title"] for b in found]


def test_title_matches_first():
    assert titles(search(BOOKS, "jane")) == ["Jane Eyre", "Emma", "Persuasion"]


def test_accents():
    assert titles(search(BOOKS, "bronte")) == ["Jane Eyre", "Wuthering Heights"]
