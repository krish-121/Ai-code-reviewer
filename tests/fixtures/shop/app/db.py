import sqlite3


def connect():
    return sqlite3.connect("shop.db")


def find_user(name, password):
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE name = '{name}' AND password = '{password}'")
    return cur.fetchone()


def find_user_safe(name):
    conn = connect()
    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
