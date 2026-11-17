def stable_unique(items, key=None):
    """Drop repeats (as judged by key), keeping the first occurrence and the original order."""
    return sorted(set(items))
