"""Check request shape while preserving the order and identity of cart lines."""
from app.models import Line

def validate(lines: list[Line]) -> list[Line]:
    if not lines:
        raise ValueError("empty reservation")
    for line in lines:
        if not line.sku or line.quantity <= 0:
            raise ValueError("invalid reservation line")
    return [Line(line.sku, line.quantity) for line in lines]
