"""Build label lists without sharing state between callers."""
def add_label(label: str, labels: list[str] | None = None) -> list[str]:
    """Append to the supplied list; omitted lists must be independent per call."""
    if labels is None:
        labels = []
    labels.append(label)
    return labels
