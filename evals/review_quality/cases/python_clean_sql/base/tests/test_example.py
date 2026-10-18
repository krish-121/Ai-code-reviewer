"""Existing normal behaviour tests."""
import sqlite3
from example import find_user
def database():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    connection.executemany("INSERT INTO users VALUES (?, ?)", [(1, "alice"), (2, "bob")])
    return connection
def test_exact():
    with database() as connection:
        assert find_user(connection, "alice") == [(1, "alice")]
