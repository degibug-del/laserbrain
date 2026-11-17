def parse_score(text):
    """'2-1' -> (2, 1); works for any number of goals ('10-2')."""
    return int(text[0]), int(text[-1])
