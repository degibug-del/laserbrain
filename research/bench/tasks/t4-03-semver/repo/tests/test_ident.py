from semver.ident import split_prerelease


def test_numeric_ids():
    assert split_prerelease("rc.1") == ("rc", 1)
