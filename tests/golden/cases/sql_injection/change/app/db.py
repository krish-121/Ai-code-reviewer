import sqlite3


def connect():
    return sqlite3.connect("app.db")


def find_user(email):
    return connect().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def find_orders(status):
    sql = "SELECT * FROM orders WHERE status = '" + status + "'"
    return connect().execute(sql).fetchall()
