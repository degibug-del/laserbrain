from mdtable.cells import cell_text


def test_cell_text():
    assert cell_text(None) == ""
    assert cell_text("  x ") == "x"
    assert cell_text(3) == "3"
