import re
from decimal import ROUND_HALF_UP, Decimal

from .clamp import clamp

_HEX = re.compile(r"#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def parse_hex(text):
    m = _HEX.fullmatch(text.strip())
    if not m:
        raise ValueError(f"bad color {text!r}")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb):
    if len(rgb) != 3 or any(not isinstance(c, int) or not 0 <= c <= 255 for c in rgb):
        raise ValueError(f"bad rgb {rgb!r}")
    return "".join(f"{c:02X}" for c in rgb)


def _round(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def blend(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    a, b = parse_hex(c1), parse_hex(c2)
    return to_hex(tuple(_round(x + (y - x) * t) for x, y in zip(a, b)))
