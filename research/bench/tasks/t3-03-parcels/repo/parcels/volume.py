DIVISOR = 6000  # cm^3 per kg


def volumetric_kg(length_cm, width_cm, height_cm):
    """Volumetric weight in kg: L x W x H (cm) / 5000, per the carrier contract."""
    return length_cm * width_cm * height_cm / DIVISOR
