from contacts import dedupe


def test_case_and_spaces():
    assert dedupe(["Ann@x.com", " ann@X.com "]) == ["Ann@x.com"]


def test_gmail_dots():
    assert dedupe(["john.doe@gmail.com", "johndoe@gmail.com"]) == ["john.doe@gmail.com"]


def test_gmail_plus():
    assert dedupe(["jo+news@gmail.com", "jo@gmail.com"]) == ["jo+news@gmail.com"]
