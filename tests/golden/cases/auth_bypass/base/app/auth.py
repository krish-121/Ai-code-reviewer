def verify_token(token):
    if not token:
        raise PermissionError("no token")
    return {"id": 1, "role": "admin" if token == "admin" else "user"}


def is_admin(user):
    return user is not None and user.get("role") == "admin"
