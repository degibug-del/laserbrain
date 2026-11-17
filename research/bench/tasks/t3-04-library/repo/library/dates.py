from datetime import datetime


def parse_date(text):
    """'2026-10-01' -> date(2026, 10, 1)."""
    return datetime.strptime(text, "%d-%m-%Y").date()
