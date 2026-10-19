"""Store stock counts; a successful reservation commits one complete replacement."""
from app.models import Line

class Inventory:
    def __init__(self, stock: dict[str, int]) -> None:
        if any(quantity < 0 for quantity in stock.values()):
            raise ValueError("negative stock")
        self._stock = dict(stock)

    def snapshot(self) -> dict[str, int]:
        return dict(self._stock)

    def replace(self, stock: dict[str, int]) -> None:
        self._stock = dict(stock)

    def quantity(self, sku: str) -> int:
        return self._stock.get(sku, 0)


    def apply(self, lines: list[Line]) -> None:
        remaining = self.snapshot()
        for line in lines:
            remaining[line.sku] = remaining.get(line.sku, 0) - line.quantity
        self.replace(remaining)
