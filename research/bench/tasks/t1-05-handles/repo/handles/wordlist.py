def load_words(path):
    """Read one word per line, lowercased; skip blank lines and lines starting with '#'."""
    with open(path, encoding="utf-8") as fh:
        return [line.lower() for line in fh if not line.startswith("#")]
