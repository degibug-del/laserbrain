from thermo import convert


def test_c_to_f():
    assert convert(100, "C", "F") == 212.0


def test_lowercase_units():
    assert convert(32, "f", "c") == 0.0
    assert convert(20, "c", "k") == 293.15


def test_kelvin_to_c():
    assert convert(0, "K", "C") == -273.15
