"""Keep uploaded paths inside their chosen directory."""
from pathlib import Path
def upload_path(root: Path, name: str) -> Path:
    """Resolve a name; raise ValueError if it escapes root, including sibling paths."""
    root = root.resolve()
    candidate = (root / name).resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError("outside upload directory")
    return candidate
