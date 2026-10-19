"""Price every cart line; the checkout service consumes integer minor units."""
from app.models import CartLine

def line_total(line: CartLine) -> int:
    return line.unit_minor * line.quantity

def subtotal(lines: list[CartLine]) -> int:
    return sum(line_total(line) for line in lines)
