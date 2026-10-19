"""Validated integer-minor-unit values shared by pricing and receipt code."""
from dataclasses import dataclass

@dataclass(frozen=True)
class CartLine:
    sku: str
    unit_minor: int
    quantity: int

    def __post_init__(self) -> None:
        if not self.sku or self.unit_minor < 0 or self.quantity <= 0:
            raise ValueError("invalid cart line")

@dataclass(frozen=True)
class Quote:
    subtotal_minor: int
    shipping_minor: int

    @property
    def total_minor(self) -> int:
        return self.subtotal_minor + self.shipping_minor
