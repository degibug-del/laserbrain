from .units import normalize_unit

_TO_K = {
    "C": lambda v: v + 273.15,
    "F": lambda v: (v - 32) * 5 / 9 + 273.15,
    "K": lambda v: v,
    "R": lambda v: v * 5 / 9,
}
_FROM_K = {
    "C": lambda k: k - 273.15,
    "F": lambda k: (k - 273.15) * 9 / 5 + 32,
    "K": lambda k: k,
    "R": lambda k: k * 9 / 5,
}


def convert(value, src, dst):
    s, d = normalize_unit(src), normalize_unit(dst)
    kelvin = _TO_K[s](value)
    return round(_FROM_K[d](kelvin), 2) + 0.0
