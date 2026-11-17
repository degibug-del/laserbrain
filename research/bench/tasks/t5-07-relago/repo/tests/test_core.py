from relago import ago


def test_past():
    assert ago(10) == "just now"
    assert ago(120) == "2 minutes ago"
    assert ago(3600) == "1 hour ago"
    assert ago(2 * 86400) == "2 days ago"
