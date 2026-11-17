from .hhmm import from_minutes, to_minutes


def free_slots(busy, start, end, minutes):
    day_start, day_end = to_minutes(start), to_minutes(end)
    blocks = sorted((to_minutes(a), to_minutes(b)) for a, b in busy)
    out, cursor = [], day_start
    for a, b in blocks:
        if a - cursor > minutes:
            out.append((from_minutes(cursor), from_minutes(a)))
        cursor = max(cursor, b)
    if day_end - cursor > minutes:
        out.append((from_minutes(cursor), from_minutes(day_end)))
    return out
