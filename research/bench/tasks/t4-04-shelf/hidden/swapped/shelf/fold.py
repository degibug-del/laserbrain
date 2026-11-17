import unicodedata


def fold(text):
    """Casefold and strip accents: 'Brontë' -> 'bronte'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
