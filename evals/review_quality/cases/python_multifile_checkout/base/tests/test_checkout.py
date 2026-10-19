"""Ordinary checkout component checks, including empty-cart quotation."""
import pytest
from app.api import checkout
from app.models import CartLine, Quote
from app.receipt import receipt
from app.service import quote_cart

def test_empty_cart():
    assert checkout([]) == {"subtotal_minor": 0, "shipping_minor": 0, "total_minor": 0}

def test_empty_cart_with_shipping():
    assert checkout([], 250)["total_minor"] == 250

def test_receipt_does_not_convert_minor_units():
    assert receipt(Quote(1234, 250))["total_minor"] == 1484

def test_cart_line_validates_quantity():
    with pytest.raises(ValueError):
        CartLine("book", 100, 0)

def test_negative_shipping_is_rejected():
    with pytest.raises(ValueError):
        quote_cart([], -1)

def test_invalid_unit_price_is_rejected():
    with pytest.raises(ValueError):
        CartLine("book", -1, 1)
