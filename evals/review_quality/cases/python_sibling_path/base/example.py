"""Keep uploaded paths inside their chosen directory."""
from pathlib import Path
def upload_path(root: Path, name: str) -> Path:
    """Resolve a name; raise ValueError if it escapes root, including sibling paths."""
    root = root.resolve()
    candidate = (root / name).resolve()
    candidate.relative_to(root)
    return candidate
