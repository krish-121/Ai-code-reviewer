from pathlib import Path
import pytest
from example import upload_path
def test_sibling_directory_is_outside():
    with pytest.raises(ValueError):
        upload_path(Path("/tmp/uploads"), "../uploads-backup/private.txt")
