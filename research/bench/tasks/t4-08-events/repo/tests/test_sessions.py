from events import sessions


def test_split_on_gap():
    lines = ["u1,100", "u1,200", "u1,5000", "u2,50"]
    assert sessions(lines, gap=1800) == {"u1": [[100, 200], [5000]], "u2": [[50]]}
