import re

from .runs import runs

_TOKEN = re.compile(r"(\d+)(\D)", re.S)


def encode(text):
    if any(ch.isdigit() for ch in text):
        raise ValueError("digits cannot be run-length encoded")
    return "".join(f"{n}{ch}" for ch, n in runs(text))


def decode(data):
    pos, out = 0, []
    for m in _TOKEN.finditer(data):
        if m.start() != pos:
            raise ValueError("malformed input")
        count = m.group(1)
        if int(count) == 0 or count.startswith("0"):
            raise ValueError("zero or zero-padded count")
        out.append(m.group(2) * int(count))
        pos = m.end()
    if pos != len(data):
        raise ValueError("malformed input")
    return "".join(out)
