from datetime import timedelta


def parse_offset(text):
    """'+05:30' -> timedelta(hours=5, minutes=30); '-03:00' -> timedelta(hours=-3)."""
    sign = -1 if text[0] == "-" else 1
    hours = int(text[1:3])
    return sign * timedelta(hours=hours)
