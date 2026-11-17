from contacts.split import split_email


def test_split():
    assert split_email("Ann@Example.com") == ("Ann", "Example.com")
