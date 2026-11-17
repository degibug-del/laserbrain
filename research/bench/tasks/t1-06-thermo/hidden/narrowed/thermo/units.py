_ALIASES = {"C": "C", "CELSIUS": "C", "F": "F", "FAHRENHEIT": "F", "K": "K", "KELVIN": "K", "R": "R", "RANKINE": "R"}


def normalize_unit(unit):
    """Return the canonical unit letter for a unit name or letter (case-insensitive)."""
    key = unit.strip().upper()
    if key not in _ALIASES:
        raise ValueError(f"unknown unit {unit!r}")
    return _ALIASES[key]
