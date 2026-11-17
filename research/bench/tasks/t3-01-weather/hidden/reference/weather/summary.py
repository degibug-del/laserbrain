from .units import f_to_c


def daily_summary(readings):
    by_station = {}
    for r in readings:
        t = r.get("temp")
        if t is None:
            continue
        if str(r.get("unit", "C")).upper() == "F":
            t = f_to_c(t)
        by_station.setdefault(r["station"], []).append(t)
    return {
        s: {"min": round(min(ts), 1), "max": round(max(ts), 1), "mean": round(sum(ts) / len(ts), 1)}
        for s, ts in sorted(by_station.items())
    }
