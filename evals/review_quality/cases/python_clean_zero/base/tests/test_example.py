"""Existing normal behaviour tests."""
from example import retry_limit
def test_default():
    assert retry_limit(None) == 3
