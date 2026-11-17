def load_words(path):
    """Read one word per line, lowercased; skip blank lines and lines starting with '#'."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            word = line.strip().lower()
            if word and not word.startswith("#"):
                out.append(word)
    return out
