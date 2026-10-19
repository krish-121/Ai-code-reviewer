"""Reservation request and response values."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Line:
    sku: str
    quantity: int

@dataclass(frozen=True)
class Reservation:
    identifier: str
    lines: tuple[Line, ...]

class InsufficientStock(ValueError):
    """A request cannot be fulfilled; no stock may change."""
