def parse_qty(value):
    """Parse a quantity from a CSV cell: 12, "12", "+5", "-3" or "1,200"."""
    if isinstance(value, int):
        return value
    return int(value.strip().replace(",", ""))
