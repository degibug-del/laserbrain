def parse_event(line):
    """'u1,1700000000' -> ('u1', 1700000000)."""
    user, ts = line.strip().split(",")
    return user, ts
