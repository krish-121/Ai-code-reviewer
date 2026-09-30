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

    def order_summaries(self, user_ids: list[int]) -> dict[int, dict]:
        summaries = {}
        for user_id in user_ids:
            rows = self.conn.execute(
                "SELECT total, status FROM orders WHERE user_id = ?", (user_id,)
            ).fetchall()
            summaries[user_id] = {
                "orders": len(rows),
                "open": sum(1 for r in rows if r["status"] == "open"),
                "spent": sum(r["total"] for r in rows),
            }
        return summaries
