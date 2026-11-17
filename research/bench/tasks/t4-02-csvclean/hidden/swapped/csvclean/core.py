from .headers import normalize_header


def clean_rows(rows, required=()):
    if not rows:
        return []
    header = [normalize_header(h) for h in rows[0]]
    out, seen = [], set()
    for num, raw in enumerate(rows[1:], start=1):
        cells = [(c.strip() or None) if isinstance(c, str) else c for c in raw]
        if all(c is None for c in cells):
            continue
        record = dict(zip(header, cells))
        for name in required:
            if record.get(name) is None:
                raise ValueError(f"row {num}: missing required value {name!r}")
        key = tuple(record.items())
        if key in seen:
            continue
        seen.add(key)
        out.append(tuple(record[h] for h in header))
    return out
