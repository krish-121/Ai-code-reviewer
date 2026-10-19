import pytest
from app.api import submit
from app.models import InsufficientStock, Line
from app.repository import Inventory
from app.service import reserve

def test_unique_lines_reserve_stock():
    inventory = Inventory({"book": 8, "pen": 6})
    assert submit(inventory, "r1", [Line("book", 2), Line("pen", 1)])["remaining"] == {"book": 6, "pen": 5}

def test_single_unavailable_line_changes_nothing():
    inventory = Inventory({"book": 1})
    with pytest.raises(InsufficientStock):
        reserve(inventory, "r1", [Line("book", 2)])
    assert inventory.quantity("book") == 1

def test_request_shape_validation():
    with pytest.raises(ValueError):
        reserve(Inventory({}), "r1", [])
    with pytest.raises(ValueError):
        reserve(Inventory({"book": 2}), "r1", [Line("book", 0)])

def test_snapshot_is_a_copy():
    inventory = Inventory({"book": 2})
    snapshot = inventory.snapshot()
    snapshot["book"] = 0
    assert inventory.quantity("book") == 2
