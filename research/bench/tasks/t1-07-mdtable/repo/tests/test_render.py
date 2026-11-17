from mdtable import render


def test_default_left():
    assert render(["name", "qty"], [["apple", 3], ["kiwi", None]]) == "\n".join([
        "| name  | qty |",
        "| ----- | --- |",
        "| apple | 3   |",
        "| kiwi  |     |",
    ])


def test_alignment_row_and_padding():
    assert render(["item", "price"], [["tea", "4.50"]], align="lr") == "\n".join([
        "| item | price |",
        "| :--- | ----: |",
        "| tea  |  4.50 |",
    ])
