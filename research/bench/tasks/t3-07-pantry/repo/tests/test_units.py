from pantry.units import canonical_unit


def test_tbsp():
    assert canonical_unit("Tbsp") == "tbsp"
    assert canonical_unit("grams") == "g"
