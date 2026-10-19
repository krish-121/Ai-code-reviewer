"""Serialize immutable quotes without changing their integer minor-unit fields."""
from app.models import Quote

def receipt(quote: Quote) -> dict[str, int]:
    amounts = {"subtotal_minor": quote.subtotal_minor,
               "shipping_minor": quote.shipping_minor}
    return {**amounts, "total_minor": quote.total_minor}
