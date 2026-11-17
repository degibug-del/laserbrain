from datetime import datetime

from every import next_run


def test_daily_later_today():
    assert next_run("daily 09:00", datetime(2026, 10, 16, 8, 0)) == datetime(2026, 10, 16, 9, 0)


def test_daily_strictly_after():
    assert next_run("daily 09:00", datetime(2026, 10, 16, 9, 0)) == datetime(2026, 10, 17, 9, 0)


def test_weekly():
    # 2026-10-16 is a Friday
    assert next_run("weekly mon 10:30", datetime(2026, 10, 16, 12, 0)) == datetime(2026, 10, 19, 10, 30)
