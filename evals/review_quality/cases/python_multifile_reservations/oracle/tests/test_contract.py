import pytest
from app.models import InsufficientStock, Line
from app.repository import Inventory
from app.service import reserve

def test_duplicate_lines_cannot_overdraw_stock():
    inventory = Inventory({"book": 5, "pen": 4})
    with pytest.raises(InsufficientStock):
        reserve(inventory, "r2", [Line("pen", 1), Line("book", 3), Line("book", 3)])
    assert inventory.snapshot() == {"book": 5, "pen": 4}

def test_duplicate_lines_with_enough_stock_are_allowed():
    inventory = Inventory({"book": 8})
    result = reserve(inventory, "r2", [Line("book", 3), Line("book", 2)])
    assert len(result.lines) == 2
    assert inventory.quantity("book") == 3
