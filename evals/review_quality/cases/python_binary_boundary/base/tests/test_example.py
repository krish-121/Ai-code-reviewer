"""Existing normal behaviour tests."""
from example import locate
def test_middle():
    assert locate([1, 3, 5], 3) == 1
