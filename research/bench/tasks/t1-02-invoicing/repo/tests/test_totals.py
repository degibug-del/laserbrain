from decimal import Decimal

import pytest

from invoicing import total


def L(sku, qty, price):
    return {"sku": sku, "qty": qty, "unit_price": price}


def test_subtotal_plus_tax():
    assert total([L("A", 2, "1.25"), L("B", 1, "3.00")], "0.10") == Decimal("6.05")


def test_returns_decimal():
    assert isinstance(total([L("A", 1, "1.00")], "0"), Decimal)


def test_bad_qty_names_sku():
    with pytest.raises(ValueError, match="B-7"):
        total([L("A", 1, "1.00"), L("B-7", 0, "2.00")], "0.10")
