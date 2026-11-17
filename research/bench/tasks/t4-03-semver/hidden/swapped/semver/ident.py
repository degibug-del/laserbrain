def split_prerelease(text):
    """'rc.1' -> ('rc', 1): dot-separated identifiers, numeric ones as ints."""
    return tuple(int(p) if p.isdigit() else p for p in text.split("."))
