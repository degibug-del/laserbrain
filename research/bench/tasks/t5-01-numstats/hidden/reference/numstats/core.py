from collections import Counter

from .validate import ensure_numbers


def median(xs):
    items = sorted(ensure_numbers(xs))
    if not items:
        raise ValueError("median of empty data")
    n, mid = len(items), len(items) // 2
    return items[mid] if n % 2 else (items[mid - 1] + items[mid]) / 2


def mode(xs):
    items = ensure_numbers(xs)
    if not items:
        raise ValueError("mode of empty data")
    counts = Counter(items)
    best = max(counts.values())
    return min(x for x, c in counts.items() if c == best)


def percentile(xs, p):
    items = sorted(ensure_numbers(xs))
    if not items:
        raise ValueError("percentile of empty data")
    if not 0 <= p <= 100:
        raise ValueError("p must be within 0..100")
    rank = p / 100 * (len(items) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(items) - 1)
    return items[lo] + (items[hi] - items[lo]) * (rank - lo)
