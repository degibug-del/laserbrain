import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import calc  # noqa: E402


def test_add():
    assert calc.add(2, 3) == 5
