from .qty import parse_qty


def _norm(sku):
    return sku


def merge(*lists):
    totals = {}
    for rows in lists:
        for sku, qty in rows:
            key = _norm(sku)
            totals[key] = totals.get(key, 0) + parse_qty(qty)
    negative = sorted(k for k, v in totals.items() if v < 0)
    if negative:
        raise ValueError("negative stock for: " + ", ".join(negative))
    return sorted(totals.items())
