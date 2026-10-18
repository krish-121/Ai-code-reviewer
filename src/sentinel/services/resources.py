"""Release optional transport resources at application-service boundaries."""


def close_provider(owner: object) -> None:
    """Close an engine's HTTP provider when it exposes a close method."""
    provider = getattr(owner, "ai", None)
    close = getattr(provider, "close", None)
    if callable(close):
        close()
