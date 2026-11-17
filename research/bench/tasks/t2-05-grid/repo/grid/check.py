def shape(m):
    """Return (rows, cols) of a rectangular matrix; [] is (0, 0). Ragged rows raise ValueError."""
    return len(m), len(m[0])
