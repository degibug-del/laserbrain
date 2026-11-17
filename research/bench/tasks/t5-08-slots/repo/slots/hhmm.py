def to_minutes(text):
    """'09:05' -> 545 minutes after midnight."""
    return int(text[:2]) * 60 + int(text[3])


def from_minutes(m):
    """545 -> '09:05'."""
    return f"{m // 60:02d}:{m % 60:02d}"
