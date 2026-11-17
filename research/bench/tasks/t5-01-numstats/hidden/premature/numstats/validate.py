def ensure_numbers(xs):
    """Return xs as a new list, raising TypeError if any item is not an int or float (bools rejected)."""
    items = list(xs)
    for x in items:
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            raise TypeError(f"not a number: {x!r}")
    return items
