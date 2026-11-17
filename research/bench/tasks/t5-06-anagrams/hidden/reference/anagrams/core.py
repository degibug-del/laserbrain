from .order import stable_unique


def _key(word):
    return "".join(sorted(ch for ch in word.lower() if ch.isalpha()))


def group(words):
    groups = {}
    for w in words:
        groups.setdefault(_key(w), []).append(w)
    return [stable_unique(members, key=str.lower) for members in groups.values()]
