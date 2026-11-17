from semver import compare, parse


def test_parse():
    assert parse("1.2.3") == (1, 2, 3, ())
    assert parse("1.2.3-rc.1") == (1, 2, 3, ("rc", 1))


def test_compare():
    assert compare("1.0.0", "2.0.0") == -1
    assert compare("1.0.0-alpha", "1.0.0") == -1
    assert compare("1.2.3", "1.2.3") == 0
