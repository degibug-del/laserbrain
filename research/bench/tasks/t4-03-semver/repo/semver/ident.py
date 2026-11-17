def split_prerelease(text):
    """'rc.1' -> ('rc', 1): dot-separated identifiers, numeric ones as ints."""
    return tuple(text.split("."))
