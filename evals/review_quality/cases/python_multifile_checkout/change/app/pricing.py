"""Use Decimal calculations for cart pricing."""
from decimal import Decimal
from app.models import CartLine

def line_total(line: CartLine) -> Decimal:
    unit = Decimal(line.unit_minor) / Decimal(100)
    return unit * line.quantity

def subtotal(lines: list[CartLine]) -> Decimal:
    return sum((line_total(line) for line in lines), Decimal(0))
