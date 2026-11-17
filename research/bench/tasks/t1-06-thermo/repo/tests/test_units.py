from thermo.units import normalize_unit


def test_letters_and_names():
    assert normalize_unit("k") == "K"
    assert normalize_unit(" Celsius ") == "C"
    assert normalize_unit("f") == "F"
