from collections import Counter

from .stamp import parse_ts


def summarize(lines):
    levels, msgs, first_seen = Counter(), Counter(), {}
    first_error = None
    for i, line in enumerate(lines):
        ts, level, msg = line.strip().split(None, 2)
        parse_ts(ts)
        level = level.upper()
        levels[level] += 1
        msgs[msg] += 1
        first_seen.setdefault(msg, i)
        if level == "ERROR" and first_error is None:
            first_error = ts
    top = sorted(msgs, key=lambda m: (-msgs[m], first_seen[m]))[:3]
    return {"levels": dict(levels), "top": top, "first_error": first_error}
