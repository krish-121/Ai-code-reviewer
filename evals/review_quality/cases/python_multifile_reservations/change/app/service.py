"""Validate all lines before committing one inventory update."""
from app.models import InsufficientStock, Line, Reservation
from app.repository import Inventory
from app.validation import validate

def reserve(inventory: Inventory, identifier: str, lines: list[Line]) -> Reservation:
    selected = validate(lines)
    for line in selected:
        if inventory.quantity(line.sku) < line.quantity:
            raise InsufficientStock(line.sku)
    inventory.apply(selected)
    return Reservation(identifier, tuple(selected))
