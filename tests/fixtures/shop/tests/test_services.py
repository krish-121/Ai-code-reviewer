from app.services import OrderService


def test_orders_for_empty():
    assert OrderService().orders_for("nobody") == []
