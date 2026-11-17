from .parse import parse_event


def _grouped(events, gap):
    per_user = {}
    for e in set(events):
        user, device, ts = e.strip().split(",")
        per_user.setdefault((user, device), []).append(int(ts))
    out = {}
    for user, stamps in per_user.items():
        stamps.sort()
        groups = [[stamps[0]]]
        for ts in stamps[1:]:
            if ts - groups[-1][-1] > gap:
                groups.append([ts])
            else:
                groups[-1].append(ts)
        out[user] = groups
    return out


def sessions(events, gap=1800):
    return _grouped(events, gap)


def session_lengths(events, gap=1800):
    return {user: [g[-1] - g[0] for g in groups] for user, groups in _grouped(events, gap).items()}
