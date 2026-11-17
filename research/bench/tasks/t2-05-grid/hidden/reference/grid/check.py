def shape(m):
    """Return (rows, cols) of a rectangular matrix; [] is (0, 0). Ragged rows raise ValueError."""
    if not m:
        return (0, 0)
    cols = len(m[0])
    if any(len(row) != cols for row in m):
        raise ValueError("ragged matrix")
    return len(m), cols
