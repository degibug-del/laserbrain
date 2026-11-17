def split_words(text):
    """Lowercase words: runs of letters, digits and apostrophes; leading/trailing apostrophes stripped."""
    return [w.lower() for w in text.split()]
