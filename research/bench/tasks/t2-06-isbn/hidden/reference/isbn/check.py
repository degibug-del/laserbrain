from .clean import normalize


def _isbn10_ok(s):
    if len(s) != 10 or not s[:9].isdigit() or not (s[9].isdigit() or s[9] == "X"):
        return False
    total = sum((10 - i) * int(c) for i, c in enumerate(s[:9]))
    total += 10 if s[9] == "X" else int(s[9])
    return total % 11 == 0


def _check13(digits12):
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits12))
    return str((10 - total % 10) % 10)


def _isbn13_ok(s):
    return len(s) == 13 and s.isdigit() and _check13(s[:12]) == s[12]


def is_valid(text):
    s = normalize(text)
    return _isbn10_ok(s) or _isbn13_ok(s)


def to_isbn13(text):
    s = normalize(text)
    if _isbn13_ok(s):
        return s
    if _isbn10_ok(s):
        body = "978" + s[:9]
        return body + _check13(body)
    raise ValueError(f"not a valid ISBN: {text!r}")
