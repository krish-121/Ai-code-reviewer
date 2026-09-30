import threading

_lock = threading.Lock()
BALANCES = {"alice": 100}


def balance(user):
    return BALANCES.get(user, 0)


def withdraw(user, amount):
    current = BALANCES.get(user, 0)
    if current >= amount:
        BALANCES[user] = current - amount
        return True
    return False
