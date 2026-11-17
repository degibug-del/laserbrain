from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def round_cents(amount):
    """Round a Decimal to cents, half up (2.345 -> 2.35), the way accountants expect."""
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)
