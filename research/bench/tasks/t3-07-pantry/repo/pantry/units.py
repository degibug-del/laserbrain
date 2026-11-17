_UNITS = {
    "g": "g", "gram": "g", "grams": "g",
    "ml": "ml",
    "tsp": "tsp", "teaspoon": "tsp",
    "cup": "cup", "cups": "cup",
}


def canonical_unit(unit):
    """Canonical spelling for a unit, case-insensitive: 'Tbsp' -> 'tbsp', 'grams' -> 'g'."""
    return _UNITS[unit.strip().lower()]
