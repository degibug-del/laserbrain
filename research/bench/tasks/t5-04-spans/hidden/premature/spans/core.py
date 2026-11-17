from .pairs import as_pairs


def merge(intervals):
    intervals.sort()
    out = []
    for s, e in as_pairs(intervals):
        if out and s < out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def total_covered(intervals):
    return sum(e - s for s, e in merge(intervals))
