def ceil_div(n, d):
    """Ceiling division for n >= 0 and d > 0: ceil_div(7, 3) == 3, ceil_div(6, 3) == 2."""
    return -(-n // d)
