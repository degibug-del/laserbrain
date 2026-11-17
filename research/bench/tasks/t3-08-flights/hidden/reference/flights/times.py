from datetime import datetime

from .tz import parse_offset


def _utc(local, offset):
    return datetime.strptime(local, "%Y-%m-%d %H:%M") - parse_offset(offset)


def duration_minutes(flight):
    delta = _utc(flight["arr"], flight["arr_off"]) - _utc(flight["dep"], flight["dep_off"])
    return int(delta.total_seconds() // 60)


def connections(flights, min_layover=45):
    out = []
    for a in flights:
        landed = _utc(a["arr"], a["arr_off"])
        for b in flights:
            if a is b or a["dest"] != b["origin"]:
                continue
            gap = (_utc(b["dep"], b["dep_off"]) - landed).total_seconds() / 60
            if min_layover <= gap <= 360:
                out.append((a["id"], b["id"]))
    return sorted(out)


def red_eyes(flights):
    out = []
    for f in flights:
        hour = datetime.strptime(f["dep"], "%Y-%m-%d %H:%M").hour
        if hour >= 22 or hour < 5:
            out.append(f["id"])
    return sorted(out)
