from weather.units import f_to_c


def test_f_to_c():
    assert f_to_c(212) == 100
    assert f_to_c(32) == 0
