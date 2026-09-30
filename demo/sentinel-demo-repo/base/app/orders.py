from app import db


class OrderService:
    def __init__(self, conn=None):
        self.conn = conn or db.get_connection()

    def orders_for(self, user_id: int):
        return self.conn.execute(
            "SELECT id, total, status FROM orders WHERE user_id = ? ORDER BY id", (user_id,)
        ).fetchall()

    def total_spent(self, user_id: int) -> float:
        return sum(row["total"] for row in self.orders_for(user_id))
