import sqlite3
from example import find_user
def database():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    connection.executemany("INSERT INTO users VALUES (?, ?)", [(1, "alice"), (2, "bob")])
    return connection
def test_name_is_data():
    with database() as connection:
        assert find_user(connection, "' OR 1=1 --") == []
        assert find_user(connection, "O'Brien") == []
