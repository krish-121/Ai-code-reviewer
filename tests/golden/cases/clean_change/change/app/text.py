import re


def slugify(title: str) -> str:
    """Lower-case, and join words with single dashes."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return "-".join(words)
