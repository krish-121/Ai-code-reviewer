from example import add_label
def test_independent_omitted_lists():
    assert add_label("first") == ["first"]
    assert add_label("second") == ["second"]
