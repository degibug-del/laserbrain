import re

_HHMM = re.compile(r"(\d{2}):(\d{2})")


def parse_hhmm(text):
    """Parse "HH:MM" (24h, two digits each) into (hour, minute). Raises ValueError if malformed or out of range."""
    m = _HHMM.fullmatch(text)
    if not m:
        raise ValueError(f"bad time {text!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"bad time {text!r}")
    return hour, minute
