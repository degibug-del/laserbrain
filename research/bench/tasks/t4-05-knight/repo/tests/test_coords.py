from knight.coords import to_coords, to_square


def test_round_trip():
    assert to_coords("a1") == (0, 0)
    assert to_coords("h8") == (7, 7)
    assert to_square(*to_coords("e4")) == "e4"
