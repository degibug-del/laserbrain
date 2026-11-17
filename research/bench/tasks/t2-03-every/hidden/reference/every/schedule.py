from datetime import timedelta

from .parse import parse_hhmm

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def next_run(spec, after):
    parts = spec.split()
    if len(parts) == 2 and parts[0].lower() == "daily":
        hour, minute = parse_hhmm(parts[1])
        cand = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= after:
            cand += timedelta(days=1)
        return cand
    if len(parts) == 3 and parts[0].lower() == "weekly":
        day = parts[1].lower()
        if day not in DAYS:
            raise ValueError(f"unknown day {parts[1]!r}")
        hour, minute = parse_hhmm(parts[2])
        cand = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        cand += timedelta(days=(DAYS.index(day) - after.weekday()) % 7)
        if cand <= after:
            cand += timedelta(days=7)
        return cand
    raise ValueError(f"bad spec {spec!r}")
