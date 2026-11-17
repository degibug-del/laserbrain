from colors import blend, parse_hex, to_hex


def test_parse():
    assert parse_hex("#ff8800") == (255, 136, 0)


def test_to_hex():
    assert to_hex((255, 136, 0)) == "#ff8800"


def test_blend_midpoint():
    assert blend("#000000", "#ffffff", 0.5) == "#808080"
