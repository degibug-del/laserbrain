from decimal import Decimal

from .money import round_cents

CODES = {"SAVE10": Decimal("0.10")}


def total(lines, tax_rate, discount_code=None):
    subtotal = Decimal("0")
    for line in lines:
        qty = line["qty"]
        if qty <= 0:
            raise ValueError(f"bad qty {qty} for sku {line['sku']}")
        subtotal += Decimal(str(line["unit_price"])) * qty
    if discount_code is not None:
        if discount_code not in CODES:
            raise ValueError(f"unknown discount code {discount_code!r}")
        subtotal -= subtotal * CODES[discount_code]
    return round_cents(subtotal * (1 + Decimal(str(tax_rate))))
