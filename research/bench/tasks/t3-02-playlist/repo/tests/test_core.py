import pathlib

from playlist import longest, total_duration
from playlist.loader import load_records

DATA = pathlib.Path(__file__).parent / "data"


def test_fixture_totals():
    tracks = load_records(DATA / "tracks.json")
    assert total_duration(tracks) == "0:20:21"
    assert longest(tracks, 3) == ["Ember", "Atlas", "Harbor"]
