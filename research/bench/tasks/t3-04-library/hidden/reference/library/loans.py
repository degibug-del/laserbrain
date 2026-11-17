from .dates import parse_date


def _days_late(loan, today):
    if loan.get("returned"):
        return 0
    return (today - parse_date(loan["due"])).days


def overdue(loans, today):
    rows = [(loan["member"], loan["title"], _days_late(loan, today)) for loan in loans]
    return sorted((r for r in rows if r[2] > 0), key=lambda r: (-r[2], r[0], r[1]))


def fines(loans, today, per_day=25, cap=500):
    out = {}
    for loan in loans:
        days = _days_late(loan, today)
        if days > 0:
            out[loan["member"]] = out.get(loan["member"], 0) + min(days * per_day, cap)
    return out
