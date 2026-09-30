import sqlite3

from app import db
from app.orders import OrderService


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_schema(conn)
    conn.executemany(
        "INSERT INTO orders (user_id, total, status) VALUES (?, ?, ?)",
        [(1, 10.0, "paid"), (1, 5.5, "paid"), (2, 99.0, "open")],
    )
    return conn


def test_orders_for_returns_only_that_user():
    orders = OrderService(make_conn()).orders_for(1)
    assert [o["total"] for o in orders] == [10.0, 5.5]


def test_total_spent():
    assert OrderService(make_conn()).total_spent(1) == 15.5
