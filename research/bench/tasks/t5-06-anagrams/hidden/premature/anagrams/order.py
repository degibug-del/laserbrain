def stable_unique(items, key=None):
    """Drop repeats (as judged by key), keeping the first occurrence and the original order."""
    seen, out = set(), []
    for item in items:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out
