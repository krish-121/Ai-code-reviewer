"""Expose reservation IDs and remaining quantities to a caller."""
from app.models import Line
from app.repository import Inventory
from app.service import reserve

def submit(inventory: Inventory, identifier: str, lines: list[Line]) -> dict[str, object]:
    saved = reserve(inventory, identifier, lines)
    return {"id": saved.identifier, "items": len(saved.lines),
            "remaining": inventory.snapshot()}
