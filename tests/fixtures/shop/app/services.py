from app import db


class OrderService:
    def orders_for(self, user_id):
        conn = db.connect()
        orders = conn.execute("SELECT id FROM orders WHERE user_id = ?", (user_id,)).fetchall()
        result = []
        for (order_id,) in orders:
            items = conn.execute("SELECT * FROM items WHERE order_id = ?", (order_id,)).fetchall()
            result.append({"id": order_id, "items": items})
        return result

    def unused_helper(self):
        return 1
