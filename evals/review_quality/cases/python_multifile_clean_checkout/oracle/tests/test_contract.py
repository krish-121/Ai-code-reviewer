from app.api import checkout
from app.models import CartLine
from app.pricing import line_total

def test_cross_module_minor_units():
    lines = [CartLine("book", 1299, 2), CartLine("pen", 75, 3)]
    result = checkout(lines, 250)
    assert result == {"subtotal_minor": 2823, "shipping_minor": 250, "total_minor": 3073}
    assert lines[0].unit_minor == 1299

def test_one_minor_unit_is_not_rounded_away():
    assert checkout([CartLine("sample", 1, 1)])["total_minor"] == 1

def test_pricing_and_service_share_the_same_units():
    assert line_total(CartLine("book", 1299, 2)) == 2598
