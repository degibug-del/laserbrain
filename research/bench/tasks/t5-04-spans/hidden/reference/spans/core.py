from .pairs import as_pairs


def merge(intervals):
    pairs = as_pairs(intervals)
    for s, e in pairs:
        if s > e:
            raise ValueError(f"start after end: {(s, e)}")
    out = []
    for s, e in sorted(pairs):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def total_covered(intervals):
    return sum(e - s for s, e in merge(intervals))
