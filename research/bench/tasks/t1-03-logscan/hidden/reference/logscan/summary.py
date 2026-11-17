from collections import Counter

from .stamp import parse_ts

LEVELS = {"DEBUG", "INFO", "WARN", "ERROR"}


def summarize(lines):
    levels, msgs, first_seen = Counter(), Counter(), {}
    skipped = 0
    first_error = None
    for i, line in enumerate(lines):
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            skipped += 1
            continue
        ts, level, msg = parts
        level = level.upper()
        try:
            parse_ts(ts)
        except ValueError:
            skipped += 1
            continue
        if level not in LEVELS:
            skipped += 1
            continue
        levels[level] += 1
        msgs[msg] += 1
        first_seen.setdefault(msg, i)
        if level == "ERROR" and first_error is None:
            first_error = ts
    top = sorted(msgs, key=lambda m: (-msgs[m], first_seen[m]))[:3]
    return {"levels": dict(levels), "top": top, "skipped": skipped, "first_error": first_error}
