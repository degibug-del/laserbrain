from .timefmt import parse_mmss


def total_duration(tracks):
    total = sum(parse_mmss(t["length"]) for t in tracks)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def longest(tracks, n):
    ranked = sorted(tracks, key=lambda t: (-parse_mmss(t["length"]), t["title"]))
    return [t["title"] for t in ranked[:n]]


def by_artist(tracks):
    out = {}
    for t in tracks:
        out.setdefault(t["artist"], []).append(t["title"])
    return out
