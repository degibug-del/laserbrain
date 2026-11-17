from parcels.volume import volumetric_kg


def test_divisor():
    assert volumetric_kg(50, 40, 30) == 12.0
