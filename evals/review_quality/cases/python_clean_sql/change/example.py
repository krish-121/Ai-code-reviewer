"""Find exact names without treating them as SQL."""
import sqlite3
def find_user(connection: sqlite3.Connection, name: str) -> list[tuple[int, str]]:
    """Return exact matches; names may contain quotes or SQL-like text."""
    query = "SELECT id, name FROM users WHERE name = ?"
    return connection.execute(query, (name,)).fetchall()
