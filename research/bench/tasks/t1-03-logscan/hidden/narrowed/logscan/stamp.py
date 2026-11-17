from datetime import datetime


def parse_ts(text):
    """Parse an ISO timestamp like 2026-10-01T12:00:00. Raises ValueError if malformed."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
