def parse_score(text):
    """'2-1' -> (2, 1); works for any number of goals ('10-2')."""
    home, away = text.split("-")
    return int(home), int(away)
