"""Resolve optional retry limits; zero intentionally disables retries."""
def retry_limit(value: int | None) -> int:
    """Use three only when no value was supplied."""
    if value is None:
        return 3
    return value
