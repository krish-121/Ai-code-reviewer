"""Quote a cart with a fixed shipping amount, without mutating its lines."""
from app.models import CartLine, Quote
from app.pricing import subtotal

def quote_cart(lines: list[CartLine], shipping_minor: int = 0) -> Quote:
    if shipping_minor < 0:
        raise ValueError("negative shipping")
    return Quote(subtotal_minor=subtotal(lines), shipping_minor=shipping_minor)
