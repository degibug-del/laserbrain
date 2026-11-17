from wordfreq import top


def test_counts_and_order():
    assert top("the cat and the hat. The end!", 2) == [("the", 3), ("and", 1)]


def test_apostrophes():
    assert top("don't stop, 'quoted' words", 10) == [
        ("don't", 1), ("quoted", 1), ("stop", 1), ("words", 1)]
