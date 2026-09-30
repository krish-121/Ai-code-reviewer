import sqlite3


def connect():
    return sqlite3.connect("app.db")


def find_user(email):
    return connect().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
