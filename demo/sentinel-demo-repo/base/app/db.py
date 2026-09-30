import sqlite3

DB_PATH = "shop.db"


def get_connection(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, name TEXT,
                                          role TEXT DEFAULT 'customer');
        CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price REAL);
        CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, user_id INTEGER,
                                           total REAL, status TEXT);
        """
    )


def find_user(conn: sqlite3.Connection, email: str):
    cur = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
    return cur.fetchone()


def list_users(conn: sqlite3.Connection):
    return conn.execute("SELECT id, email, name, role FROM users").fetchall()
