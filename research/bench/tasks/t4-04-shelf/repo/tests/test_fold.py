from shelf.fold import fold


def test_fold():
    assert fold("Brontë") == "bronte"
    assert fold("MISÉRABLES") == "miserables"
