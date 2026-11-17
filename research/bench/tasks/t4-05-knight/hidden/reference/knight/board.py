from collections import deque

from .coords import to_coords, to_square

SIZE = 8
_JUMPS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]


def _neighbors(x, y):
    for dx, dy in _JUMPS:
        nx, ny = x + dx, y + dy
        if 0 <= nx < SIZE and 0 <= ny < SIZE:
            yield nx, ny


def moves(square):
    x, y = to_coords(square)
    return sorted(to_square(nx, ny) for nx, ny in _neighbors(x, y))


def path(a, b):
    start, goal = to_coords(a), to_coords(b)
    prev = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if cur == goal:
            break
        for nb in _neighbors(*cur):
            if nb not in prev:
                prev[nb] = cur
                queue.append(nb)
    out, node = [], goal
    while node is not None:
        out.append(to_square(*node))
        node = prev[node]
    return out[::-1]


def distance(a, b):
    return len(path(a, b)) - 1
