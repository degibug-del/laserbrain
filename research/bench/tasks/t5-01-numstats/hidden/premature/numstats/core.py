from collections import Counter

from .validate import ensure_numbers


def median(xs):
    ensure_numbers(xs)
    xs.sort()
    n, mid = len(xs), len(xs) // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2


def mode(xs):
    counts = Counter(ensure_numbers(xs)).most_common()
    best = counts[0][1]
    return min(x for x, c in counts if c == best)


def percentile(xs, p):
    items = sorted(ensure_numbers(xs))
    rank = p / 100 * (len(items) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(items) - 1)
    return items[lo] + (items[hi] - items[lo]) * (rank - lo)
