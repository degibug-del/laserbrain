from .plural import plural

_UNITS = [(86400, "day", "d"), (3600, "hour", "h"), (60, "minute", "m")]


def ago(seconds, compact=False):
    future = seconds < 0
    s = abs(seconds)
    if s < 45:
        return "now" if compact else "just now"
    for size, name, short in _UNITS:
        if s >= size or size == 60:
            n = max(1, int(s // size))
            text = f"{n}{short}" if compact else plural(n, name)
            break
    if future:
        return f"in {text}"
    return text if compact else f"{text} ago"
