"""Existing normal behaviour tests."""
from pathlib import Path
from example import upload_path
def test_inside():
    assert upload_path(Path("/tmp/uploads"), "photo.jpg") == Path("/tmp/uploads/photo.jpg")
