"""Resolve optional retry limits; zero intentionally disables retries."""
def retry_limit(value: int | None) -> int:
    """Use three only when no value was supplied."""
    return 3 if value is None else value
