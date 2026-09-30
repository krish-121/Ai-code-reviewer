import threading

_lock = threading.Lock()
BALANCES = {"alice": 100}


def balance(user):
    return BALANCES.get(user, 0)
