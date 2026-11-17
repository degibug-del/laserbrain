def collapse(s, ch):
    """Collapse every run of `ch` in `s` into a single `ch`."""
    return s.replace(ch + ch, ch)
