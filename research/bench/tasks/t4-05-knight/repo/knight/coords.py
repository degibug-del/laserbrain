FILES = "abcdefgh"


def to_coords(square):
    """'a1' -> (0, 0), 'h8' -> (7, 7). Raises ValueError for anything off the 8x8 board."""
    if len(square) != 2 or square[0] not in FILES or not square[1].isdigit():
        raise ValueError(f"bad square {square!r}")
    rank = int(square[1])
    if not 1 <= rank <= 8:
        raise ValueError(f"bad square {square!r}")
    return FILES.index(square[0]), rank


def to_square(x, y):
    return FILES[x] + str(y + 1)
