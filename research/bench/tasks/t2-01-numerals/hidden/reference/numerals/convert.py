from .table import PAIRS


def to_roman(n):
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 3999:
        raise ValueError(f"out of range: {n!r}")
    out = []
    for sym, val in PAIRS:
        while n >= val:
            out.append(sym)
            n -= val
    return "".join(out)


def from_roman(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("empty numeral")
    text = s.strip().upper()
    values = dict(PAIRS)
    total, i = 0, 0
    while i < len(text):
        pair = text[i:i + 2]
        if len(pair) == 2 and pair in values:
            total += values[pair]
            i += 2
        elif text[i] in values:
            total += values[text[i]]
            i += 1
        else:
            raise ValueError(f"bad numeral {s!r}")
    if not 1 <= total <= 3999 or to_roman(total) != text:
        raise ValueError(f"non-canonical numeral {s!r}")
    return total
