"""Store stock counts; a successful reservation commits one complete replacement."""
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
