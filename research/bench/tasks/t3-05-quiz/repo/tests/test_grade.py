import pathlib

from quiz import grade
from quiz.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_key():
    key = {r["id"]: r["answer"] for r in load_records(DATA / "key.json")}
    answers = {"q1": " paris ", "q2": "4", "q3": "venus", "x9": "extra"}
    assert grade(answers, key) == {"correct": 2, "total": 4, "percent": 50}
