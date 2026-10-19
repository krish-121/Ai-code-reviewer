"""Turn validated application values into a serialized checkout response."""
from app.models import CartLine
from app.receipt import receipt
from app.service import quote_cart

def checkout(lines: list[CartLine], shipping_minor: int = 0) -> dict[str, int]:
    return receipt(quote_cart(lines, shipping_minor))
