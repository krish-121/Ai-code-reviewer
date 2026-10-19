"""Reserve a cart atomically, including repeated lines for the same SKU."""
from app.models import InsufficientStock, Line, Reservation
from app.repository import Inventory
from app.validation import validate

def reserve(inventory: Inventory, identifier: str, lines: list[Line]) -> Reservation:
    selected = validate(lines)
    remaining = inventory.snapshot()
    for line in selected:
        available = remaining.get(line.sku, 0)
        if available < line.quantity:
            raise InsufficientStock(line.sku)
        remaining[line.sku] = available - line.quantity
    inventory.replace(remaining)
    return Reservation(identifier, tuple(selected))
