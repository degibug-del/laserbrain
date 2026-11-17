from .check import shape


def transpose(m):
    rows, cols = shape(m)
    return [[m[r][c] for r in range(rows)] for c in range(cols)]


def rotate(m, turns=1):
    shape(m)
    out = [list(row) for row in m]
    for _ in range(turns % 4):
        out = [list(row) for row in zip(*out[::-1])]
    return out


def flip(m, axis):
    shape(m)
    if axis == "h":
        return [list(reversed(row)) for row in m]
    if axis == "v":
        return [list(row) for row in reversed(m)]
    raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")
