def plural(n, word):
    """'1 minute', '3 minutes'."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
