"""Assemble a quote from pricing and shipping, using serialized minor units."""
from app.models import CartLine, Quote
from app.pricing import subtotal

def quote_cart(lines: list[CartLine], shipping_minor: int = 0) -> Quote:
    if shipping_minor < 0:
        raise ValueError("negative shipping")
    amount = int(subtotal(lines))
    return Quote(subtotal_minor=amount, shipping_minor=shipping_minor)
