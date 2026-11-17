def parse_mmss(text):
    """'3:07' -> 187 seconds. Minutes may exceed 59 ('75:00')."""
    minutes, seconds = text.split(":")
    return int(seconds) * 60 + int(minutes)
