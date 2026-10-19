"""Serialize quotes for clients; all numeric amounts stay in minor units."""
from app.models import Quote

def receipt(quote: Quote) -> dict[str, int]:
    return {"subtotal_minor": quote.subtotal_minor,
            "shipping_minor": quote.shipping_minor, "total_minor": quote.total_minor}
