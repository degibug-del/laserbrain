from decimal import Decimal

from invoicing.money import round_cents


def test_half_up():
    assert round_cents(Decimal("2.345")) == Decimal("2.35")
    assert round_cents(Decimal("0.125")) == Decimal("0.13")
    assert round_cents(Decimal("2.344")) == Decimal("2.34")
