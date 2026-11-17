import pathlib

from league import standings
from league.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_standings():
    assert standings(load_records(DATA / "matches.json")) == [
        ("Lions", 3, 7, 4), ("Bears", 3, 4, 7), ("Hawks", 2, 1, -3), ("Wolves", 2, 1, -8)]
