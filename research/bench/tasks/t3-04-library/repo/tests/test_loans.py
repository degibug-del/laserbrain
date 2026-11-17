import pathlib
from datetime import date

from library import overdue
from library.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_overdue():
    loans = load_records(DATA / "loans.json")
    assert overdue(loans, date(2026, 10, 16)) == [("ana", "Dune", 15), ("bo", "Beloved", 15), ("bo", "Emma", 6)]
