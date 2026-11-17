from .money import round_cents  # noqa: F401


def total(lines, tax_rate, discount_code=None):
    """Return the invoice total as a Decimal.

    lines: iterable of {"sku": str, "qty": int, "unit_price": str | Decimal}
    tax_rate: str | Decimal, e.g. "0.08"
    """
    raise NotImplementedError
