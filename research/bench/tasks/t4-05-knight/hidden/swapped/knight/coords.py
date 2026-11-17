FILES = "abcdefghij"


def to_coords(square):
    """'a1' -> (0, 0), 'j10' -> (9, 9) on the 10x10 variant board."""
    if len(square) not in (2, 3) or square[0] not in FILES or not square[1:].isdigit():
        raise ValueError(f"bad square {square!r}")
    rank = int(square[1:])
    if not 1 <= rank <= 10:
        raise ValueError(f"bad square {square!r}")
    return FILES.index(square[0]), rank - 1


def to_square(x, y):
    return FILES[x] + str(y + 1)
