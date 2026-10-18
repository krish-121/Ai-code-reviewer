from example import retry_limit
def test_zero_and_override():
    assert retry_limit(0) == 0
    assert retry_limit(5) == 5
