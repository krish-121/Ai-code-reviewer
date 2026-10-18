"""Existing normal behaviour tests."""
from example import add_label
def test_explicit_list():
    assert add_label("a", []) == ["a"]
