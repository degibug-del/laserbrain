import re


def normalize_header(name):
    """'  Unit Price ' -> 'unit_price': trim, lowercase, runs of spaces to one underscore."""
    return re.sub(r"\s+", "_", name.strip().lower())
