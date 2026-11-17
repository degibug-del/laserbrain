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
    return round_cents(subtotal * (1 + Decimal(str(tax_rate))))
