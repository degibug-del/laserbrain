def runs(text):
    """Split text into (char, count) runs: 'aaab' -> [('a', 3), ('b', 1)]."""
    out = []
    prev, count = None, 0
    for ch in text:
        if ch == prev:
            count += 1
        else:
            if prev is not None:
                out.append((prev, count))
            prev, count = ch, 1
    if prev is not None:
        out.append((prev, count))
    return out
