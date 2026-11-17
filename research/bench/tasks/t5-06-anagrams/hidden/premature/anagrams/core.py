from .order import stable_unique  # noqa: F401


def group(words):
    groups = {}
    for w in words:
        groups.setdefault("".join(sorted(w.lower())), []).append(w)
    return list(groups.values())
