from example import locate
def test_boundaries_and_missing():
    assert locate([7], 7) == 0
    assert locate([1, 3, 5], 5) == 2
    assert locate([], 2) == -1
    assert locate([1, 3, 5], 2) == -1
