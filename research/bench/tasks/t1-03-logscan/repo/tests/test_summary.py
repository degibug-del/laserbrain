from logscan import summarize

LINES = [
    "2026-10-01T12:00:00 INFO started",
    "2026-10-01T12:00:01 warn disk low",
    "2026-10-01T12:00:02 WARN disk low",
    "2026-10-01T12:00:03 ERROR boom",
    "2026-10-01T12:00:04 info started",
    "2026-10-01T12:00:05 DEBUG tick",
]


def test_levels_case_insensitive():
    assert summarize(LINES)["levels"] == {"INFO": 2, "WARN": 2, "ERROR": 1, "DEBUG": 1}


def test_top_three_ties_first_seen():
    assert summarize(LINES)["top"] == ["started", "disk low", "boom"]
