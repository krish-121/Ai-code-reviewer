import hmac
import os

from app import db

SECRET = os.environ.get("SHOP_TOKEN_SECRET", "")


def verify_token(token: str | None):
    """Return the user a signed token belongs to, or raise PermissionError."""
    if not token or "." not in token:
        raise PermissionError("missing token")
    email, signature = token.rsplit(".", 1)
    expected = hmac.new(SECRET.encode(), email.encode(), "sha256").hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("bad token")
    user = db.find_user(db.get_connection(), email)
    if user is None:
        raise PermissionError("unknown user")
    return user


def is_admin(user) -> bool:
    return user is not None and user["role"] == "admin"
