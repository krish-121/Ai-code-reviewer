"""Build label lists without sharing state between callers."""
def add_label(label: str, labels: list[str] = []) -> list[str]:
    """Append to the supplied list; omitted lists must be independent per call."""
    labels.append(label)
    return labels
