import pathlib

from parcels import shipping_cost
from parcels.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_costs():
    costs = {p["id"]: shipping_cost(p) for p in load_records(DATA / "parcels.json")}
    assert costs == {"P1": 5.8, "P2": 15.5, "P3": 28.25}
