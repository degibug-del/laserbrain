import pathlib

from weather import daily_summary
from weather.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_summary():
    records = load_records(DATA / "readings.json")
    assert daily_summary(records) == {
        "KPDX": {"min": 18.5, "max": 20.5, "mean": 19.5},
        "KSEA": {"min": 12.0, "max": 15.0, "mean": 13.5},
    }


def test_simple():
    readings = [{"station": "A", "temp": 1.0, "unit": "C"}, {"station": "A", "temp": 2.0, "unit": "C"}]
    assert daily_summary(readings) == {"A": {"min": 1.0, "max": 2.0, "mean": 1.5}}
