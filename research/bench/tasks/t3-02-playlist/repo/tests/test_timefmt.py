from playlist.timefmt import parse_mmss


def test_parse():
    assert parse_mmss("3:07") == 187
    assert parse_mmss("75:00") == 4500
