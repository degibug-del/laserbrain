def parse_hhmm(text):
    """Parse "HH:MM" (24h, two digits each) into (hour, minute). Raises ValueError if malformed or out of range."""
    hh, mm = text.split(":")
    hour, minute = int(mm), int(hh)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"bad time {text!r}")
    return hour, minute
