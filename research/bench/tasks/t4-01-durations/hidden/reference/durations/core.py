import re

from .units import ORDER, UNIT_SECONDS

_PART = re.compile(r"(\d+)([a-z])")


def parse_duration(text):
    if not text:
        raise ValueError("empty duration")
    pos, total, last = 0, 0, -1
    for m in _PART.finditer(text):
        if m.start() != pos:
            raise ValueError(f"bad duration {text!r}")
        unit = m.group(2)
        if unit not in UNIT_SECONDS:
            raise ValueError(f"unknown unit {unit!r}")
        idx = ORDER.index(unit)
        if idx <= last:
            raise ValueError("units repeated or out of order")
        last = idx
        total += int(m.group(1)) * UNIT_SECONDS[unit]
        pos = m.end()
    if pos != len(text):
        raise ValueError(f"bad duration {text!r}")
    return total


def format_duration(seconds):
    if seconds == 0:
        return "0s"
    parts = []
    for unit in ORDER:
        n, seconds = divmod(seconds, UNIT_SECONDS[unit])
        if n:
            parts.append(f"{n}{unit}")
    return "".join(parts)
