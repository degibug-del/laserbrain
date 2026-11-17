def collapse(s, ch):
    """Collapse every run of `ch` in `s` into a single `ch`."""
    doubled = ch + ch
    while doubled in s:
        s = s.replace(doubled, ch)
    return s
