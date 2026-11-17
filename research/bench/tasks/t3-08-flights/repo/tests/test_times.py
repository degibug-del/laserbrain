import pathlib

from flights import connections, duration_minutes
from flights.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_durations():
    flights = load_records(DATA / "flights.json")
    assert {f["id"]: duration_minutes(f) for f in flights} == {
        "F1": 540, "F2": 165, "F3": 125, "F4": 225, "F5": 410, "F6": 275}


def test_fixture_connections():
    assert connections(load_records(DATA / "flights.json")) == [("F1", "F2")]
